from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Awaitable, Callable, Dict, Optional

from redis.asyncio import Redis
from websockets.asyncio.server import ServerConnection

from kungfu_chess.server.accounts_client import AccountsClient
from kungfu_chess.server.game_room import GameRoom
from kungfu_chess.server.move_log_stream import MoveLogStream
from kungfu_chess.server.redis_client import get_client as get_redis_client
from kungfu_chess.server.room_shard_registry import LEASE_TTL_MS, RoomShardRegistry

LEASE_RENEWAL_SECONDS = 2.0  # comfortably under the TTL, so a slow tick never lets the lease lapse on a live room

logger = logging.getLogger(__name__)


class RoomAllocationError(Exception):
    """Raised if a room's lease is already held by another worker - see
    GameAllocator.allocate. Today there's only ever one worker (this
    same process) with either a fresh uuid (ELO match) or a room name
    RoomRegistry already guarantees is only handed to one caller (Room
    Create/Join), so this path is not expected to trigger in practice
    yet - but the lease is real and enforced now, ahead of the
    multi-worker world where a second Game Allocator racing to place
    the same room is the exact scenario section 3 exists to prevent."""


class GameAllocator:
    """The placement decision (Server_Design.md section 1's "Game
    Allocator" row), deliberately separate from the Matchmaker's
    fairness decision (section 7): given a freshly-matched pair, this
    decides which worker hosts the game and acquires that worker's
    lease on the room (section 3) before the room is handed back to
    play. "Which worker" for a *brand-new* room is still just whichever
    replica Kubernetes' own Service load-balancing happened to route
    this HostSeatMessage to (no custom picking logic here) - but the
    lease itself is acquired, renewed by heartbeat, and released for
    real, and a crashed worker's now-expired lease is exactly what lets
    a *different* replica's game_shard.py rebuild an orphaned room from
    JetStream replay (see room_shard_registry.py's own save_meta/
    load_meta and game_shard.py's _handle_reconnect)."""

    def __init__(
        self,
        accounts_client: AccountsClient,
        redis_client: Optional[Redis] = None,
        namespace: str = "",
        move_log_stream: Optional[MoveLogStream] = None,
        shard_address: Optional[str] = None,
    ) -> None:
        self._accounts_client = accounts_client
        self._redis = redis_client or get_redis_client()
        self._namespace = namespace
        # None in every test that doesn't care about crash recovery -
        # forwarded straight through to each GameRoom this allocates
        # (Server_Design.md section 3).
        self._move_log_stream = move_log_stream
        self._registry = RoomShardRegistry(self._redis, namespace)
        # This worker's own advertised address (Server_Design.md section
        # 3) - the lease's actual *value*, not just an opaque id, so
        # ws_gateway.py can resolve an existing room_id to the shard
        # that owns it (see room_shard_registry.py) instead of assuming
        # it's always the same fixed one. Falls back to a random id for
        # callers/tests that don't pass a real address - production
        # (game_shard.py's run()) always does.
        self._worker_id = shard_address or uuid.uuid4().hex
        self._lease_renewal_tasks: Dict[str, asyncio.Task] = {}

    def set_shard_address(self, shard_address: str) -> None:
        """Updates the advertised address after construction - only
        needed where it isn't known until after startup (a test's
        ephemeral port, bound to 0 and assigned by the OS - see
        tests/unit/conftest.py's shard_address fixture); production
        always knows its address upfront (game_shard.py's run()) and
        never needs this. Safe to call any time before the first
        allocate() - nothing reads self._worker_id before then."""
        self._worker_id = shard_address

    def _lease_key(self, lease_id: str) -> str:
        return self._registry.key(lease_id)

    async def allocate(
        self,
        white_ws: ServerConnection, white_username: str,
        black_ws: ServerConnection, black_username: str,
        room_id: Optional[str] = None,
        on_game_over: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> GameRoom:
        """Acquires this room's lease, then builds (but does not start)
        the GameRoom that will actually run it - the caller (Matchmaker)
        still owns calling room.start() and tracking the result in its
        own _rooms dict, same as before this split. lease_id is the
        room's own name for a Create/Join room (already guaranteed
        unique while pending by RoomRegistry), or a fresh uuid for an
        ELO-matched room, which has no player-chosen name at all."""
        lease_id = room_id or uuid.uuid4().hex
        if lease_id in self._lease_renewal_tasks:
            # This exact instance already has a live renewal loop for
            # this room - a genuine second allocate() call for it (a
            # bug, a race) must still fail regardless of what
            # confirm_or_acquire below would say (its own address would
            # trivially "match itself"). Checked first, before ever
            # touching Redis, so this stays true independent of the
            # Agones-flow change just below.
            raise RoomAllocationError(f"room lease {lease_id!r} is already held by another worker")
        # confirm_or_acquire, not a fresh acquire(nx=True) (Server_Design.md
        # section 3, Stage 7): matchmaker.py's own Agones allocation call
        # may already have written this exact lease - naming *this*
        # worker's own address - before this method ever runs, once a
        # room's placement decision moves upstream of _build_room. A
        # plain acquire(nx=True) would see "key exists" and fail every
        # room in that world; this recognizes "the existing value is
        # already my own address" as success and takes over heartbeat
        # renewal, while still refusing (RoomAllocationError) if a
        # *different* worker's address is already there - the same
        # conflict case acquire() used to guard against.
        confirmed = await self._registry.confirm_or_acquire(lease_id, self._worker_id, ttl_ms=LEASE_TTL_MS)
        if not confirmed:
            raise RoomAllocationError(f"room lease {lease_id!r} is already held by another worker")

        async def release() -> None:
            await self._release_lease(lease_id)
            if on_game_over is not None:
                await on_game_over()

        room = GameRoom(
            white_ws=white_ws, white_username=white_username,
            black_ws=black_ws, black_username=black_username,
            accounts_client=self._accounts_client, room_id=room_id,
            on_game_over=release,
            move_log_stream=self._move_log_stream,
        )
        self._lease_renewal_tasks[lease_id] = asyncio.create_task(self._renew_lease(lease_id))
        return room

    async def _renew_lease(self, lease_id: str) -> None:
        """Heartbeat, section 3: while this worker actually still holds
        the room, keep pushing the lease's expiry back out - so only a
        worker that stops renewing (crashed, or genuinely done) ever
        lets it lapse. The compare-and-renew (only if the stored value
        is still this worker's own address) is what actually lets
        multiple workers safely share this Redis instance - see
        room_shard_registry.py's own atomic renew script."""
        try:
            while True:
                await asyncio.sleep(LEASE_RENEWAL_SECONDS)
                await self._registry.renew(lease_id, self._worker_id, ttl_ms=LEASE_TTL_MS)
        except asyncio.CancelledError:
            pass

    async def _release_lease(self, lease_id: str) -> None:
        task = self._lease_renewal_tasks.pop(lease_id, None)
        if task is not None:
            task.cancel()
        await self._registry.release(lease_id)

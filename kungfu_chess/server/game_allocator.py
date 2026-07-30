from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Awaitable, Callable, Dict, Optional

from redis.asyncio import Redis
from websockets.asyncio.server import ServerConnection

from kungfu_chess.server.accounts_client import AccountsClient
from kungfu_chess.server.game_room import GameRoom
from kungfu_chess.server.redis_client import get_client as get_redis_client

LEASE_TTL_MS = 5000  # Server_Design.md section 3's own example: SET room:<id>:owner <worker> NX PX 5000
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
    play. Still one process for now (section 19's Stage 3) - "picking
    a worker" has nothing to choose between yet, since this process is
    the only one - but the lease itself is acquired, renewed by
    heartbeat, and released for real, so the Redis schema and failure
    behavior already match the design this is a stepping stone toward."""

    def __init__(
        self,
        accounts_client: AccountsClient,
        redis_client: Optional[Redis] = None,
        namespace: str = "",
    ) -> None:
        self._accounts_client = accounts_client
        self._redis = redis_client or get_redis_client()
        self._namespace = namespace
        # A fresh id per GameAllocator instance - in production there's
        # only ever one process/allocator, so this never needs to
        # persist across a restart; a crashed worker's leases simply
        # expire (no renewal ever arrives) rather than needing to be
        # explicitly reclaimed under the old id.
        self._worker_id = uuid.uuid4().hex
        self._lease_renewal_tasks: Dict[str, asyncio.Task] = {}

    def _lease_key(self, lease_id: str) -> str:
        return f"room:{self._namespace}:{lease_id}:owner"

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
        acquired = await self._redis.set(self._lease_key(lease_id), self._worker_id, nx=True, px=LEASE_TTL_MS)
        if not acquired:
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
        )
        self._lease_renewal_tasks[lease_id] = asyncio.create_task(self._renew_lease(lease_id))
        return room

    async def _renew_lease(self, lease_id: str) -> None:
        """Heartbeat, section 3: while this worker actually still holds
        the room, keep pushing the lease's expiry back out - so only a
        worker that stops renewing (crashed, or genuinely done) ever
        lets it lapse. XX (only-if-exists) rather than a plain SET
        guards against re-creating a lease that's already expired and
        possibly been claimed by someone else - it deliberately does
        NOT check that the value is still our own worker_id first
        (that would need a compare-and-set), since with a single
        worker today nothing else is ever writing this key regardless."""
        try:
            while True:
                await asyncio.sleep(LEASE_RENEWAL_SECONDS)
                await self._redis.set(self._lease_key(lease_id), self._worker_id, xx=True, px=LEASE_TTL_MS)
        except asyncio.CancelledError:
            pass

    async def _release_lease(self, lease_id: str) -> None:
        task = self._lease_renewal_tasks.pop(lease_id, None)
        if task is not None:
            task.cancel()
        await self._redis.delete(self._lease_key(lease_id))

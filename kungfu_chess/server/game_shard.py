from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from prometheus_client import Gauge
from redis.asyncio import Redis
from websockets.asyncio.server import ServerConnection, serve

from kungfu_chess.logging_config import configure_logging
from kungfu_chess.model.piece import BLACK, WHITE
from kungfu_chess.server import shard_protocol
from kungfu_chess.server.accounts_client import ACCOUNTS_SERVICE_URL, AccountsClient
from kungfu_chess.server.accounts_client import get_client as get_accounts_client
from kungfu_chess.server.game_allocator import GameAllocator, RoomAllocationError
from kungfu_chess.server.game_room import GameRoom
from kungfu_chess.server.messages import LeaveRoomMessage, LeftRoomMessage
from kungfu_chess.server.metrics import start_metrics_server
from kungfu_chess.server.move_log_stream import MoveLogStream
from kungfu_chess.server.redis_client import get_client as get_redis_client
from kungfu_chess.server.room_shard_registry import RoomShardRegistry
from kungfu_chess.server.rooms import RoomRegistry
from kungfu_chess.server.serialization import deserialize_message, serialize_message

# Server_Design.md section 1: this role's own named scaling metric is
# active-room count (alongside CPU, which Prometheus's own process/cpu
# collectors already cover generically - no bespoke metric needed for that half).
ACTIVE_ROOMS = Gauge("game_shard_active_rooms", "Live GameRooms this worker currently hosts")

# Env-overridable (Stage 5, section 17) - and deliberately double-duty:
# this module's own run()/main() use it as the address to *bind*, while
# ws_gateway.py imports the very same constant as the address it
# *dials* to reach the Shard. That only works today because both live
# in one process on "localhost"; in docker-compose the two processes
# are different containers reading their own environment, so each sets
# SHARD_HOST independently - the game-shard container sets it to
# "0.0.0.0" (bind every interface), the ws-gateway container sets it to
# "game-shard" (the compose service's DNS name) - no code conflict,
# since os.environ.get() runs at import time inside whichever
# container's process imports this module.
SHARD_HOST = os.environ.get("SHARD_HOST", "localhost")
SHARD_PORT = int(os.environ.get("SHARD_PORT", "8767"))
# A third, genuinely separate purpose from SHARD_HOST's existing double
# duty above (Server_Design.md section 3): the address this worker
# advertises into the room_shard_registry - what ws_gateway.py resolves
# an *existing* room_id to for reconnect/spectate, not what this
# process binds to (0.0.0.0 isn't dialable) and not what a *different*
# container's own SHARD_HOST happens to be set to. Defaults to
# "SHARD_HOST:SHARD_PORT", correct for local/single-process dev where
# SHARD_HOST really is a dialable "localhost" - docker-compose.yml sets
# it explicitly to "game-shard:8767" instead.
SHARD_ADVERTISED_ADDRESS = os.environ.get("SHARD_ADVERTISED_ADDRESS", f"{SHARD_HOST}:{SHARD_PORT}")
LOG_FILE = "game_shard.log"
PENDING_ROOM_TIMEOUT_SECONDS = 10  # bounds how long the first seat of a brand-new room waits for the second

logger = logging.getLogger(__name__)


@dataclass
class _SeatArrival:
    ws: ServerConnection
    username: str
    opponent_username: str


@dataclass
class _PendingRoom:
    """Bookkeeping for a brand-new room while only one seat's relay
    connection has arrived (Server_Design.md sections 2/3/15, Stage
    4a). The first HostSeatMessage for a given room_id creates this
    and waits on `ready`; the second one actually builds the GameRoom
    (see GameShard._build_room) and wakes both waiters."""

    seats: Dict[str, _SeatArrival] = field(default_factory=dict)  # color -> arrival
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    room: Optional[GameRoom] = None
    failed: bool = False


class GameShard:
    """Server_Design.md sections 2/3/15 (Stage 4a): hosts every live
    GameRoom this worker owns. Reached only by the WS Gateway's relay
    connections - never a real client socket directly, the Gateway is
    the only thing between a player and here (see ws_gateway.py's
    relay-mode pump). GameAllocator and RoomRegistry move here
    wholesale from Matchmaker - Stage 3's fairness/placement split
    stays the same, it's just now physically relocated to wherever
    the room actually lives, which is this process, not the Gateway's."""

    def __init__(
        self,
        accounts_client: AccountsClient,
        redis_client: Optional[Redis] = None,
        namespace: str = "",
        move_log_stream: Optional[MoveLogStream] = None,
        shard_address: Optional[str] = None,
    ) -> None:
        self._accounts_client = accounts_client
        redis_client = redis_client or get_redis_client()
        self._move_log_stream = move_log_stream
        self._game_allocator = GameAllocator(
            accounts_client=accounts_client, redis_client=redis_client, namespace=namespace,
            move_log_stream=move_log_stream, shard_address=shard_address,
        )
        self._room_registry = RoomRegistry(redis_client=redis_client, namespace=namespace)
        # Same namespace/Redis as the lease GameAllocator itself acquires
        # (room:<ns>:<id>:owner) - only ever used here for the durable
        # white/black pairing (room:<ns>:<id>:meta - see its own
        # save_meta/load_meta docstring), which is what makes _build_room
        # callable again on a *different* worker after this room's
        # original owner crashed, not just on the one that first built it.
        self._room_shard_registry = RoomShardRegistry(redis_client, namespace)
        self._rooms: Dict[str, GameRoom] = {}
        self._pending: Dict[str, _PendingRoom] = {}
        ACTIVE_ROOMS.set_function(lambda: len(self._rooms))

    def set_shard_address(self, shard_address: str) -> None:
        """See GameAllocator.set_shard_address's own docstring - a
        test-only escape hatch for an ephemeral port not known until
        after the server actually starts."""
        self._game_allocator.set_shard_address(shard_address)

    async def handle_connection(self, ws: ServerConnection) -> None:
        """The one entry point websockets.serve dispatches every relay
        connection to - reads exactly one routing handshake message,
        then hands off to whichever case it names."""
        try:
            raw = await ws.recv()
        except Exception as error:
            logger.debug("relay connection closed before its routing handshake: %s", error)
            return
        try:
            routing = shard_protocol.recv_routing_message(raw)
        except (ValueError, KeyError, TypeError) as error:
            logger.warning("malformed routing handshake: %s", error)
            return

        if isinstance(routing, shard_protocol.HostSeatMessage):
            await self._handle_host_seat(ws, routing)
        elif isinstance(routing, shard_protocol.ReconnectMessage):
            await self._handle_reconnect(ws, routing)
        elif isinstance(routing, shard_protocol.SpectateMessage):
            await self._handle_spectate(ws, routing)
        else:
            logger.warning("unrecognized routing message: %r", routing)

    async def _handle_host_seat(self, ws: ServerConnection, routing: shard_protocol.HostSeatMessage) -> None:
        pending = self._pending.setdefault(routing.room_id, _PendingRoom())
        pending.seats[routing.color] = _SeatArrival(
            ws=ws, username=routing.username, opponent_username=routing.opponent_username
        )

        if len(pending.seats) < 2:
            try:
                await asyncio.wait_for(pending.ready.wait(), timeout=PENDING_ROOM_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                # The other seat's relay connection never arrived (Gateway<->Shard
                # blip, or it failed on its own side) - give up silently rather than
                # leaving this connection open forever. The player sees no explicit
                # "that failed" message, just the ordinary "kicked back to lobby"
                # behavior closing this socket already produces (ws_gateway.py) -
                # a known, deliberately simple limitation for this stage.
                logger.warning("room %s: the other seat never arrived - giving up", routing.room_id)
                self._pending.pop(routing.room_id, None)
                await ws.close()
                return
        else:
            await self._build_room(routing.room_id, pending)

        if pending.failed or pending.room is None:
            await ws.close()
            return
        await self._run_seat_messages(ws, pending.room, routing.color)

    async def _build_room(self, room_id: str, pending: _PendingRoom) -> None:
        white = pending.seats.get(WHITE)
        black = pending.seats.get(BLACK)
        if white is None or black is None:
            pending.failed = True
            pending.ready.set()
            return
        try:
            room = await self._game_allocator.allocate(
                white_ws=white.ws, white_username=white.username,
                black_ws=black.ws, black_username=black.username,
                room_id=room_id,
                on_game_over=lambda: self._release_room(room_id),
            )
        except RoomAllocationError as error:
            logger.warning("room %s: allocation failed: %s", room_id, error)
            pending.failed = True
            pending.ready.set()
            self._pending.pop(room_id, None)
            return
        if self._move_log_stream is not None:
            # Server_Design.md sections 3/20.5: almost always empty (a
            # room_id is normally brand new the one time _build_room ever
            # runs for it) - non-empty specifically identifies the
            # crash-recovery case, reconstructing the board/cooldown state
            # this worker never itself witnessed happening.
            replayed = await self._move_log_stream.replay_moves(room_id)
            if replayed:
                logger.info("room %s: replaying %d recorded move(s) from JetStream", room_id, len(replayed))
                room.replay(replayed)
        # Durable, unlike self._rooms - see save_meta's own docstring on
        # why this is what lets _handle_reconnect rebuild this exact
        # pairing on a *different* worker later, if this one crashes.
        await self._room_shard_registry.save_meta(room_id, white.username, black.username)
        self._rooms[room_id] = room
        pending.room = room
        await room.start()
        self._pending.pop(room_id, None)
        pending.ready.set()

    async def _handle_reconnect(self, ws: ServerConnection, routing: shard_protocol.ReconnectMessage) -> None:
        room = self._rooms.get(routing.room_id)
        if room is not None:
            if not await room.try_reconnect(routing.color, ws):
                await ws.close()  # expired grace period - the Gateway falls back to the lobby
                return
            await self._run_seat_messages(ws, room, routing.color)
            return

        # Not hosted here. Two very different reasons that can be true,
        # both landing on whatever worker a Kubernetes Service happened
        # to route this relay connection to (there is no session
        # affinity - same reasoning as matchmaking_service.py's own
        # per-connection state, section 3): this worker genuinely never
        # saw this room (a routine reconnect, misrouted to a sibling
        # replica), or this room's *original* worker crashed and this
        # is the recovery path - room_meta (durable - see save_meta)
        # is what tells the two apart, since self._rooms itself can't
        # (a crashed worker's in-memory dict is simply gone, taking the
        # answer with it). Reuses the exact same "wait for the other
        # seat, then _build_room" flow _handle_host_seat already has -
        # a genuine crash recovery is expected to bring *both* players'
        # own Gateways here at nearly the same moment (see
        # ws_gateway.py's own automatic-retry-on-shard-failure), so the
        # very same pairing-wait naturally handles it; if only one
        # actually shows up, this times out exactly like an abandoned
        # brand-new room does today - a known, deliberately simple limit
        # for this stage, not a silent gap (see Server_Design.md).
        meta = await self._room_shard_registry.load_meta(routing.room_id)
        if meta is None:
            await ws.close()  # never existed, or already long gone - the Gateway falls back to the lobby
            return
        white_username, black_username = meta
        opponent_username = black_username if routing.color == WHITE else white_username
        pending = self._pending.setdefault(routing.room_id, _PendingRoom())
        pending.seats[routing.color] = _SeatArrival(ws=ws, username=routing.username, opponent_username=opponent_username)

        if len(pending.seats) < 2:
            try:
                await asyncio.wait_for(pending.ready.wait(), timeout=PENDING_ROOM_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                logger.warning("room %s: recovery abandoned - the other seat never reconnected", routing.room_id)
                self._pending.pop(routing.room_id, None)
                await ws.close()
                return
        else:
            await self._build_room(routing.room_id, pending)

        if pending.failed or pending.room is None:
            await ws.close()
            return
        await self._run_seat_messages(ws, pending.room, routing.color)

    async def _handle_spectate(self, ws: ServerConnection, routing: shard_protocol.SpectateMessage) -> None:
        room = self._rooms.get(routing.room_id)
        if room is None:
            await ws.close()
            return
        await room.add_spectator(ws)
        try:
            async for _ in ws:
                pass  # a spectator never sends anything meaningful - just wait for it to close
        except Exception as error:
            logger.debug("spectator relay connection closed: %s", error)
        finally:
            room.remove_spectator(ws)

    async def _run_seat_messages(self, ws: ServerConnection, room: GameRoom, color: str) -> None:
        """The relocated body of what used to be Matchmaker._leave_room
        plus on_disconnect's room-branch - now here, since this Shard
        is the only process left holding the live GameRoom (Stage 4a)."""
        left_via_button = False
        try:
            async for raw in ws:
                try:
                    message = deserialize_message(raw)
                except (ValueError, KeyError, TypeError) as error:
                    logger.warning("dropping malformed message from %s: %s", room.username_of(color), error)
                    continue
                if isinstance(message, LeaveRoomMessage):
                    if not room.is_game_over():
                        continue
                    also_leaving = await room.leave(ws)
                    await self._safe_send(ws, LeftRoomMessage())
                    for other_ws in also_leaving:
                        await self._safe_send(other_ws, LeftRoomMessage())
                        await other_ws.close()  # the entire "kicked back to lobby" signal ws_gateway.py needs
                    left_via_button = True
                    return
                await room.handle_message(color, message)
        finally:
            if not left_via_button:
                if room.is_game_over():
                    for other_ws in await room.leave(ws):
                        await self._safe_send(other_ws, LeftRoomMessage())
                        await other_ws.close()
                else:
                    await room.handle_disconnect(color)

    async def _safe_send(self, ws: ServerConnection, message: Any) -> None:
        try:
            await ws.send(serialize_message(message))
        except Exception as error:
            logger.debug("send failed on a closed/broken relay connection: %s", error)

    async def _release_room(self, room_id: str) -> None:
        await self._room_registry.close(room_id)
        await self._room_shard_registry.clear_meta(room_id)
        self._rooms.pop(room_id, None)


async def run(host: str = SHARD_HOST, port: int = SHARD_PORT, accounts_service_url: str = ACCOUNTS_SERVICE_URL) -> None:
    accounts_client = get_accounts_client(accounts_service_url)
    # Server_Design.md section 3: one NATS connection, reused for every
    # room this worker ever hosts - if this raises (NATS unreachable),
    # this process fails to start rather than silently running without
    # crash recovery, since docker-compose.yml declares NATS a hard
    # dependency of this role.
    move_log_stream = await MoveLogStream.connect()
    shard = GameShard(
        accounts_client=accounts_client, move_log_stream=move_log_stream, shard_address=SHARD_ADVERTISED_ADDRESS
    )
    async with serve(shard.handle_connection, host, port):
        logger.info("Kung Fu Chess Game Shard listening on ws://%s:%s", host, port)
        await asyncio.Future()  # runs until the process is killed


def main() -> None:
    configure_logging(LOG_FILE)
    start_metrics_server()
    asyncio.run(run())


if __name__ == "__main__":
    main()

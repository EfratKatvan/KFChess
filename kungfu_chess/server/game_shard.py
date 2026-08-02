from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

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
from kungfu_chess.server.redis_client import get_client as get_redis_client
from kungfu_chess.server.rooms import RoomRegistry
from kungfu_chess.server.serialization import deserialize_message, serialize_message

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
    ) -> None:
        self._accounts_client = accounts_client
        redis_client = redis_client or get_redis_client()
        self._game_allocator = GameAllocator(accounts_client=accounts_client, redis_client=redis_client, namespace=namespace)
        self._room_registry = RoomRegistry(redis_client=redis_client, namespace=namespace)
        self._rooms: Dict[str, GameRoom] = {}
        self._pending: Dict[str, _PendingRoom] = {}

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
        self._rooms[room_id] = room
        pending.room = room
        await room.start()
        self._pending.pop(room_id, None)
        pending.ready.set()

    async def _handle_reconnect(self, ws: ServerConnection, routing: shard_protocol.ReconnectMessage) -> None:
        room = self._rooms.get(routing.room_id)
        if room is None or not await room.try_reconnect(routing.color, ws):
            await ws.close()  # missing room or expired grace period - the Gateway falls back to the lobby
            return
        await self._run_seat_messages(ws, room, routing.color)

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
        self._rooms.pop(room_id, None)


async def run(host: str = SHARD_HOST, port: int = SHARD_PORT, accounts_service_url: str = ACCOUNTS_SERVICE_URL) -> None:
    accounts_client = get_accounts_client(accounts_service_url)
    shard = GameShard(accounts_client=accounts_client)
    async with serve(shard.handle_connection, host, port):
        logger.info("Kung Fu Chess Game Shard listening on ws://%s:%s", host, port)
        await asyncio.Future()  # runs until the process is killed


def main() -> None:
    configure_logging(LOG_FILE)
    asyncio.run(run())


if __name__ == "__main__":
    main()

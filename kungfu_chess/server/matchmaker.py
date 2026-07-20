from __future__ import annotations

import asyncio
from typing import Dict, Optional

from websockets.asyncio.server import ServerConnection

from kungfu_chess.server import protocol
from kungfu_chess.server.game_room import GameRoom
from kungfu_chess.server.messages import NoOpponentFoundMessage, WaitingForOpponentMessage
from kungfu_chess.server.serialization import deserialize_message, serialize_message


class Matchmaker:
    """Pairs connecting players into GameRooms. At most one connection
    ever waits at a time - the instant a second player connects, they're
    matched (first-come = White, second = Black) into their own
    independent GameRoom, freeing the matchmaker to pair whoever
    connects next. A lone waiting player who isn't matched within
    protocol.MATCHMAKING_TIMEOUT_SECONDS gets a "no opponent found"
    message instead of waiting forever."""

    def __init__(self) -> None:
        self._waiting: Optional[ServerConnection] = None
        self._waiting_timeout_task: Optional[asyncio.Task] = None
        self._rooms: Dict[ServerConnection, GameRoom] = {}

    async def on_connect(self, ws: ServerConnection) -> None:
        if self._waiting is None:
            self._waiting = ws
            await ws.send(serialize_message(WaitingForOpponentMessage()))
            self._waiting_timeout_task = asyncio.create_task(self._timeout_waiting(ws))
            return

        opponent = self._waiting
        self._cancel_waiting_timeout()
        self._waiting = None

        room = GameRoom(white_ws=opponent, black_ws=ws)
        self._rooms[opponent] = room
        self._rooms[ws] = room
        await room.start()

    async def on_message(self, ws: ServerConnection, raw: str) -> None:
        room = self._rooms.get(ws)
        if room is None:
            return
        try:
            message = deserialize_message(raw)
        except (ValueError, KeyError, TypeError):
            return  # malformed/unrecognized message from a client - ignore, don't crash the room
        color = room.color_of(ws)
        if color is not None:
            await room.handle_message(color, message)

    async def on_disconnect(self, ws: ServerConnection) -> None:
        if self._waiting is ws:
            self._cancel_waiting_timeout()
            self._waiting = None
            return

        room = self._rooms.get(ws)
        if room is None:
            return
        room.stop()
        for other_ws in [connection for connection, r in self._rooms.items() if r is room]:
            del self._rooms[other_ws]

    async def _timeout_waiting(self, ws: ServerConnection) -> None:
        await asyncio.sleep(protocol.MATCHMAKING_TIMEOUT_SECONDS)
        if self._waiting is not ws:
            return  # already matched or already disconnected
        self._waiting = None
        self._waiting_timeout_task = None
        await ws.send(serialize_message(NoOpponentFoundMessage()))

    def _cancel_waiting_timeout(self) -> None:
        if self._waiting_timeout_task is not None:
            self._waiting_timeout_task.cancel()
            self._waiting_timeout_task = None

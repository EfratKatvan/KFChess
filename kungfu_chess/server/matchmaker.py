from __future__ import annotations

import asyncio
from typing import Dict, Optional, Tuple

from websockets.asyncio.server import ServerConnection

from kungfu_chess.server import protocol
from kungfu_chess.server.accounts import DEFAULT_DB_PATH
from kungfu_chess.server.game_room import GameRoom
from kungfu_chess.server.messages import LoginFailedMessage, NoOpponentFoundMessage, WaitingForOpponentMessage
from kungfu_chess.server.serialization import deserialize_message, serialize_message


class Matchmaker:
    """Pairs connecting, already-authenticated players into GameRooms. At
    most one connection ever waits at a time - the instant a second
    player connects, they're matched (first-come = White, second =
    Black) into their own independent GameRoom, freeing the matchmaker
    to pair whoever connects next. A lone waiting player who isn't
    matched within protocol.MATCHMAKING_TIMEOUT_SECONDS gets a "no
    opponent found" message instead of waiting forever.

    Also routes reconnections: if a username that just disconnected
    from a live GameRoom logs back in within the room's grace period,
    it's reattached to that same room/color instead of re-entering
    matchmaking - see GameRoom.handle_disconnect/try_reconnect.

    A username can only ever have one *live* connection at a time - a
    second simultaneous login (before the first disconnects) is
    rejected outright, rather than silently entering matchmaking and
    potentially getting paired against itself."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        self._waiting: Optional[Tuple[ServerConnection, str]] = None
        self._waiting_timeout_task: Optional[asyncio.Task] = None
        self._rooms: Dict[ServerConnection, GameRoom] = {}
        self._disconnected_players: Dict[str, Tuple[GameRoom, str]] = {}
        self._active_connections: Dict[str, ServerConnection] = {}  # username -> its one live connection

    async def on_connect(self, ws: ServerConnection, username: str) -> bool:
        """Returns False (and sends LoginFailedMessage itself) if this
        username already has a live connection elsewhere - the caller
        should close the socket without entering matchmaking/message
        handling for it."""
        if username in self._active_connections:
            await ws.send(serialize_message(
                LoginFailedMessage(reason="this account is already connected from another window")
            ))
            return False
        self._active_connections[username] = ws

        pending = self._disconnected_players.pop(username, None)
        if pending is not None:
            room, color = pending
            if await room.try_reconnect(color, ws):
                self._rooms[ws] = room
                return True
            # grace period already expired (race) - fall through to normal matchmaking below

        if self._waiting is None:
            self._waiting = (ws, username)
            await ws.send(serialize_message(WaitingForOpponentMessage()))
            self._waiting_timeout_task = asyncio.create_task(self._timeout_waiting(ws))
            return True

        opponent_ws, opponent_username = self._waiting
        self._cancel_waiting_timeout()
        self._waiting = None

        room = GameRoom(
            white_ws=opponent_ws, white_username=opponent_username,
            black_ws=ws, black_username=username,
            db_path=self._db_path,
        )
        self._rooms[opponent_ws] = room
        self._rooms[ws] = room
        await room.start()
        return True

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
        username = next((u for u, connection in self._active_connections.items() if connection is ws), None)
        if username is not None:
            del self._active_connections[username]

        if self._waiting is not None and self._waiting[0] is ws:
            self._cancel_waiting_timeout()
            self._waiting = None
            return

        room = self._rooms.pop(ws, None)
        if room is None:
            return
        color = room.color_of(ws)
        if color is None:
            return

        room_username = room.username_of(color)
        self._disconnected_players[room_username] = (room, color)
        await room.handle_disconnect(color)
        asyncio.create_task(self._forget_if_still_pending(room_username, room))

    async def _forget_if_still_pending(self, username: str, room: GameRoom) -> None:
        """Cleans up the reconnect-routing entry once the grace period
        (plus a small buffer) has passed - if the player never came
        back, GameRoom has already auto-resigned by then, so this entry
        would otherwise just linger forever pointing at a finished
        game."""
        await asyncio.sleep(protocol.DISCONNECT_GRACE_SECONDS + 1)
        pending = self._disconnected_players.get(username)
        if pending is not None and pending[0] is room:
            del self._disconnected_players[username]

    async def _timeout_waiting(self, ws: ServerConnection) -> None:
        await asyncio.sleep(protocol.MATCHMAKING_TIMEOUT_SECONDS)
        if self._waiting is None or self._waiting[0] is not ws:
            return  # already matched or already disconnected
        self._waiting = None
        self._waiting_timeout_task = None
        await ws.send(serialize_message(NoOpponentFoundMessage()))

    def _cancel_waiting_timeout(self) -> None:
        if self._waiting_timeout_task is not None:
            self._waiting_timeout_task.cancel()
            self._waiting_timeout_task = None

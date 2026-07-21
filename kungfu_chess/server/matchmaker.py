from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from websockets.asyncio.server import ServerConnection

from kungfu_chess.server import protocol
from kungfu_chess.server.accounts import DEFAULT_DB_PATH
from kungfu_chess.server.game_room import GameRoom
from kungfu_chess.server.messages import (
    LoginFailedMessage,
    NoOpponentFoundMessage,
    SeekGameMessage,
    WaitingForOpponentMessage,
)
from kungfu_chess.server.serialization import deserialize_message, serialize_message


@dataclass
class _Seeker:
    """One player currently in the waiting pool, i.e. has clicked
    "Play" and hasn't been matched yet."""

    ws: ServerConnection
    username: str
    rating: int
    timeout_task: asyncio.Task


class Matchmaker:
    """Logging in only lands a connection in the lobby - matchmaking
    itself is opt-in, triggered by a SeekGameMessage (the "Play"
    button). Any number of players can be seeking at once; a new
    seeker is paired with the first already-waiting seeker whose
    rating is within protocol.MATCHMAKING_ELO_RANGE, first-come =
    White, second = Black, into their own independent GameRoom. A
    seeker who isn't matched within protocol.MATCHMAKING_TIMEOUT_SECONDS
    gets a "no opponent found" message instead of waiting forever.

    Also routes reconnections: if a username that just disconnected
    from a live GameRoom logs back in within the room's grace period,
    it's reattached to that same room/color instead of landing back in
    the lobby - see GameRoom.handle_disconnect/try_reconnect.

    A username can only ever have one *live* connection at a time - a
    second simultaneous login (before the first disconnects) is
    rejected outright, rather than silently entering the lobby and
    potentially seeking against itself."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        self._waiting: Dict[ServerConnection, _Seeker] = {}
        self._rooms: Dict[ServerConnection, GameRoom] = {}
        self._disconnected_players: Dict[str, Tuple[GameRoom, str]] = {}
        self._active_connections: Dict[str, ServerConnection] = {}  # username -> its one live connection
        self._ratings: Dict[str, int] = {}  # username -> rating, as of its current connection's login

    async def on_connect(self, ws: ServerConnection, username: str, rating: int) -> bool:
        """Returns False (and sends LoginFailedMessage itself) if this
        username already has a live connection elsewhere - the caller
        should close the socket without entering the lobby/message
        handling for it."""
        if username in self._active_connections:
            await ws.send(serialize_message(
                LoginFailedMessage(reason="this account is already connected from another window")
            ))
            return False
        self._active_connections[username] = ws
        self._ratings[username] = rating

        pending = self._disconnected_players.pop(username, None)
        if pending is not None:
            room, color = pending
            if await room.try_reconnect(color, ws):
                self._rooms[ws] = room
                return True
            # grace period already expired (race) - fall through, lands in the lobby like a fresh login

        return True

    async def on_message(self, ws: ServerConnection, raw: str) -> None:
        room = self._rooms.get(ws)
        try:
            message = deserialize_message(raw)
        except (ValueError, KeyError, TypeError):
            return  # malformed/unrecognized message from a client - ignore, don't crash the room
        if room is not None:
            color = room.color_of(ws)
            if color is not None:
                await room.handle_message(color, message)
        elif isinstance(message, SeekGameMessage):
            await self._start_seeking(ws)

    async def _start_seeking(self, ws: ServerConnection) -> None:
        if ws in self._waiting:
            return  # already seeking - a second Play click while waiting is a no-op
        username = next((u for u, connection in self._active_connections.items() if connection is ws), None)
        if username is None:
            return
        rating = self._ratings[username]

        opponent = self._find_opponent_within_elo_range(rating)
        if opponent is not None:
            del self._waiting[opponent.ws]
            opponent.timeout_task.cancel()
            room = GameRoom(
                white_ws=opponent.ws, white_username=opponent.username,
                black_ws=ws, black_username=username,
                db_path=self._db_path,
            )
            self._rooms[opponent.ws] = room
            self._rooms[ws] = room
            await room.start()
            return

        await ws.send(serialize_message(WaitingForOpponentMessage()))
        timeout_task = asyncio.create_task(self._timeout_waiting(ws))
        self._waiting[ws] = _Seeker(ws=ws, username=username, rating=rating, timeout_task=timeout_task)

    def _find_opponent_within_elo_range(self, rating: int) -> Optional[_Seeker]:
        for seeker in self._waiting.values():
            if abs(seeker.rating - rating) <= protocol.MATCHMAKING_ELO_RANGE:
                return seeker
        return None

    async def on_disconnect(self, ws: ServerConnection) -> None:
        username = next((u for u, connection in self._active_connections.items() if connection is ws), None)
        if username is not None:
            del self._active_connections[username]
            del self._ratings[username]

        seeker = self._waiting.pop(ws, None)
        if seeker is not None:
            seeker.timeout_task.cancel()
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
        seeker = self._waiting.pop(ws, None)
        if seeker is None:
            return  # already matched or already disconnected
        await ws.send(serialize_message(NoOpponentFoundMessage()))

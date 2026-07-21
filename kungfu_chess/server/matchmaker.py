from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from websockets.asyncio.server import ServerConnection

from kungfu_chess.server import accounts, protocol
from kungfu_chess.server.accounts import DEFAULT_DB_PATH
from kungfu_chess.server.game_room import GameRoom
from kungfu_chess.server.messages import (
    CancelRoomMessage,
    CreateRoomFailedMessage,
    CreateRoomMessage,
    JoinRoomFailedMessage,
    JoinRoomMessage,
    LoginFailedMessage,
    NoOpponentFoundMessage,
    RoomCancelledMessage,
    RoomCreatedMessage,
    SeekGameMessage,
    SpectatingMessage,
    WaitingForOpponentMessage,
)
from kungfu_chess.server.rooms import RoomError, RoomRegistry
from kungfu_chess.server.serialization import deserialize_message, serialize_message

logger = logging.getLogger(__name__)


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

        # The Room dialog's Create/Join/Cancel flow - independent of, and
        # parallel to, the ELO-proximity _waiting queue above.
        self._room_registry = RoomRegistry()
        self._room_games: Dict[str, GameRoom] = {}  # room_id -> its started GameRoom
        self._pending_room_creators: Dict[ServerConnection, str] = {}  # ws -> room_id, only while no opponent has joined yet

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
                logger.info("%s reconnected as %s", username, color)
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
        elif isinstance(message, CreateRoomMessage):
            await self._create_room(ws, message.room_id)
        elif isinstance(message, JoinRoomMessage):
            await self._join_room(ws, message.room_id)
        elif isinstance(message, CancelRoomMessage):
            await self._cancel_room(ws)

    async def _start_seeking(self, ws: ServerConnection) -> None:
        if ws in self._waiting:
            return  # already seeking - a second Play click while waiting is a no-op
        username = self._username_of(ws)
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
            logger.info("matched %s (white) vs %s (black)", opponent.username, username)
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

    def _username_of(self, ws: ServerConnection) -> Optional[str]:
        return next((u for u, connection in self._active_connections.items() if connection is ws), None)

    async def _create_room(self, ws: ServerConnection, room_id: str) -> None:
        username = self._username_of(ws)
        if username is None:
            return
        try:
            room = self._room_registry.create(username, room_id)
        except RoomError as error:
            await ws.send(serialize_message(CreateRoomFailedMessage(reason=str(error))))
            return
        self._pending_room_creators[ws] = room.room_id
        logger.info("room %s created by %s", room.room_id, username)
        await ws.send(serialize_message(RoomCreatedMessage(room_id=room.room_id)))

    async def _join_room(self, ws: ServerConnection, room_id: str) -> None:
        username = self._username_of(ws)
        if username is None:
            return
        try:
            room = self._room_registry.join(room_id, username)
        except RoomError as error:
            await ws.send(serialize_message(JoinRoomFailedMessage(reason=str(error))))
            return

        if room.opponent_username == username:
            # This join just filled the opponent seat - per the spec, the
            # second person to join is Black; the creator is always White.
            creator_ws = self._active_connections.get(room.creator_username)
            self._pending_room_creators.pop(creator_ws, None)
            game_room = GameRoom(
                white_ws=creator_ws, white_username=room.creator_username,
                black_ws=ws, black_username=username,
                db_path=self._db_path, room_id=room.room_id,
                on_game_over=lambda: self._close_room(room.room_id),
            )
            self._room_games[room.room_id] = game_room
            self._rooms[creator_ws] = game_room
            self._rooms[ws] = game_room
            logger.info("room %s: %s joined as black - game starting", room.room_id, username)
            await game_room.start()
            return

        # The room already had an opponent - this join is a spectator.
        game_room = self._room_games[room.room_id]
        self._rooms[ws] = game_room
        logger.info("room %s: %s joined as a spectator", room.room_id, username)
        await game_room.add_spectator(ws)
        await ws.send(serialize_message(SpectatingMessage(
            room_id=room.room_id,
            white_username=room.creator_username,
            white_rating=accounts.get_rating(self._db_path, room.creator_username),
            black_username=room.opponent_username,
            black_rating=accounts.get_rating(self._db_path, room.opponent_username),
        )))

    async def _cancel_room(self, ws: ServerConnection) -> None:
        username = self._username_of(ws)
        if username is None:
            return
        try:
            self._room_registry.cancel(username)
        except RoomError:
            return  # race: an opponent just joined - MatchFoundMessage is already on its way instead
        self._pending_room_creators.pop(ws, None)
        logger.info("room cancelled by %s", username)
        await ws.send(serialize_message(RoomCancelledMessage()))

    def _close_room(self, room_id: str) -> None:
        self._room_registry.close(room_id)
        self._room_games.pop(room_id, None)

    async def on_disconnect(self, ws: ServerConnection) -> None:
        username = self._username_of(ws)
        if username is not None:
            del self._active_connections[username]
            del self._ratings[username]

        seeker = self._waiting.pop(ws, None)
        if seeker is not None:
            seeker.timeout_task.cancel()
            return

        pending_room_id = self._pending_room_creators.pop(ws, None)
        if pending_room_id is not None:
            # The creator vanished before anyone joined - just free the id,
            # there's no GameRoom or opponent to notify yet.
            logger.info("room %s abandoned (creator %s disconnected before anyone joined)", pending_room_id, username)
            self._room_registry.close(pending_room_id)
            return

        room = self._rooms.pop(ws, None)
        if room is None:
            return
        color = room.color_of(ws)
        if color is None:
            # A spectator's disconnect is a plain no-op cleanup - it must
            # never enter the pause/reconnect-grace path below, which is
            # reserved for the two real players.
            room.remove_spectator(ws)
            logger.info("%s left as a spectator", username)
            return

        room_username = room.username_of(color)
        logger.info("%s disconnected mid-game", room_username)
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

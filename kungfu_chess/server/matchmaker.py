from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional, Tuple, Type

from redis.asyncio import Redis
from websockets.asyncio.server import ServerConnection

from kungfu_chess.server import accounts, protocol
from kungfu_chess.server.accounts import DEFAULT_DB_PATH
from kungfu_chess.server.game_room import GameRoom
from kungfu_chess.server.messages import (
    CancelRoomMessage,
    CancelSeekMessage,
    CreateRoomFailedMessage,
    CreateRoomMessage,
    JoinRoomFailedMessage,
    JoinRoomMessage,
    LeaveRoomMessage,
    LeftRoomMessage,
    LoginFailedMessage,
    NoOpponentFoundMessage,
    RoomCancelledMessage,
    RoomCreatedMessage,
    SeekCancelledMessage,
    SeekGameMessage,
    SpectatingMessage,
    WaitingForOpponentMessage,
)
from kungfu_chess.server.redis_client import get_client as get_redis_client
from kungfu_chess.server.rooms import RoomError, RoomRegistry
from kungfu_chess.server.serialization import deserialize_message, serialize_message

logger = logging.getLogger(__name__)


@dataclass
class _WaitingLocal:
    """The half of a waiting seeker (has clicked "Play", not yet
    matched) that can't live in Redis - the live socket and its
    timeout task. The rating itself lives only as the seekers-queue
    ZSET's score (see Matchmaker._start_seeking) - not duplicated
    here, so there's exactly one place it can go stale."""

    ws: ServerConnection
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

    def __init__(self, db_path: str = DEFAULT_DB_PATH, redis_client: Optional[Redis] = None) -> None:
        self._db_path = db_path
        self._redis = redis_client or get_redis_client()
        # A per-instance namespace, not a fixed key: production only ever
        # constructs one Matchmaker, so this changes nothing there - it
        # exists so that separate Matchmaker instances (chiefly separate
        # tests) never see each other's entries in the one shared Redis
        # server, without needing any explicit flush/teardown (an empty
        # ZSET or an explicitly-deleted key just disappears on its own).
        self._namespace = uuid.uuid4().hex
        self._seekers_queue_key = f"seekers:queue:{self._namespace}"
        self._waiting: Dict[str, _WaitingLocal] = {}  # username -> its local (non-Redis) bookkeeping
        self._rooms: Dict[ServerConnection, GameRoom] = {}
        self._disconnected_players: Dict[str, Tuple[GameRoom, str]] = {}
        self._active_connections: Dict[str, ServerConnection] = {}  # username -> its one live connection

        # The Room dialog's Create/Join/Cancel flow - independent of, and
        # parallel to, the ELO-proximity _waiting queue above. Shares this
        # Matchmaker's Redis client and per-instance namespace, same as
        # the seekers queue.
        self._room_registry = RoomRegistry(redis_client=self._redis, namespace=self._namespace)
        self._room_games: Dict[str, GameRoom] = {}  # room_id -> its started GameRoom
        self._pending_room_creators: Dict[ServerConnection, str] = {}  # ws -> room_id, only while no opponent has joined yet

        # Dispatch table for messages from a connection that isn't in a
        # GameRoom yet (still in the lobby) - one handler per message
        # kind, in place of a growing if/elif isinstance chain.
        self._lobby_handlers: Dict[Type[object], Callable[[ServerConnection, object], Awaitable[None]]] = {
            SeekGameMessage: self._start_seeking,
            CancelSeekMessage: self._cancel_seeking,
            CreateRoomMessage: self._create_room,
            JoinRoomMessage: self._join_room,
            CancelRoomMessage: self._cancel_room,
        }

        # Checked before room-routing in on_message, since a connection
        # still in self._rooms would otherwise always go straight to
        # room.handle_message and never reach here - the "Back to
        # Lobby" button on the game-over overlay is the only message a
        # room-bound connection can send that isn't gameplay.
        self._room_exit_handlers: Dict[Type[object], Callable[[ServerConnection, object], Awaitable[None]]] = {
            LeaveRoomMessage: self._leave_room,
        }

    async def _safe_send(self, ws: ServerConnection, message: object) -> None:
        try:
            await ws.send(serialize_message(message))
        except Exception as error:
            # the connection this was meant for may itself be mid-disconnect
            # (e.g. both players of a finished game leaving around the same
            # time) - never let that take down the caller's own cleanup.
            logger.debug("send failed on a closed/broken socket: %s", error)

    async def on_connect(self, ws: ServerConnection, username: str) -> bool:
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
        except (ValueError, KeyError, TypeError) as error:
            logger.warning("dropping malformed message from %s: %s", self._username_of(ws), error)
            return  # malformed/unrecognized message from a client - ignore, don't crash the room
        if room is not None:
            exit_handler = self._room_exit_handlers.get(type(message))
            if exit_handler is not None:
                await exit_handler(ws, message)
                return
            color = room.color_of(ws)
            if color is not None:
                await room.handle_message(color, message)
            return
        handler = self._lobby_handlers.get(type(message))
        if handler is not None:
            await handler(ws, message)

    async def _leave_room(self, ws: ServerConnection, message: LeaveRoomMessage) -> None:
        """The "Back to Lobby" button on the game-over overlay - only
        takes effect once the game has actually ended; a stray/raced
        click before that is just ignored, since gameplay messages are
        still routed to the room as normal. Room registry/rating
        cleanup already happened at game-over time (see GameRoom's
        on_game_over callback) - this frees the leaving connection to
        go through self._lobby_handlers again, and - if it was a real
        player, not a spectator - does the same for their now-partnerless
        opponent too (see GameRoom.leave, which also stops the room's
        tick loop for good, so it can never broadcast a stale board to
        either connection again after they've moved on)."""
        room = self._rooms.get(ws)
        if room is None or not room.is_game_over():
            return
        also_leaving = await room.leave(ws)
        del self._rooms[ws]
        await self._safe_send(ws, LeftRoomMessage())
        for other_ws in also_leaving:
            self._rooms.pop(other_ws, None)
            await self._safe_send(other_ws, LeftRoomMessage())

    async def _start_seeking(self, ws: ServerConnection, message: SeekGameMessage) -> None:
        username = self._username_of(ws)
        if username is None or username in self._waiting:
            return  # not logged in, or a second Play click while waiting - both no-ops
        # Fetched fresh rather than cached from login, since a player who
        # has already finished one or more games this session has a
        # rating that's since moved in the database - a stale snapshot
        # could approve (or refuse) a match that no longer reflects
        # either player's real current rating.
        rating = accounts.get_rating(self._db_path, username)

        opponent_username = await self._claim_opponent_within_elo_range(rating)
        if opponent_username is not None:
            opponent = self._waiting.pop(opponent_username, None)
            if opponent is not None:
                opponent.timeout_task.cancel()
                room = GameRoom(
                    white_ws=opponent.ws, white_username=opponent_username,
                    black_ws=ws, black_username=username,
                    db_path=self._db_path,
                )
                self._rooms[opponent.ws] = room
                self._rooms[ws] = room
                logger.info("matched %s (white) vs %s (black)", opponent_username, username)
                await room.start()
                return
            # Claimed them in the Redis queue, but they're already gone
            # from local bookkeeping (disconnected/cancelled in the
            # narrow window between the two) - either way they're no
            # longer queued, so just fall through and treat this seeker
            # as unmatched instead.
            logger.info("claimed opponent %s but they'd already left - %s stays unmatched", opponent_username, username)

        timeout_task = asyncio.create_task(self._timeout_waiting(username))
        self._waiting[username] = _WaitingLocal(ws=ws, timeout_task=timeout_task)
        await ws.send(serialize_message(WaitingForOpponentMessage()))
        await self._redis.zadd(self._seekers_queue_key, {username: rating})

    async def _cancel_seeking(self, ws: ServerConnection, message: CancelSeekMessage) -> None:
        """The Back button on the "Waiting for opponent..." screen - the
        Play-button counterpart to _cancel_room."""
        username = self._username_of(ws)
        local = self._waiting.pop(username, None) if username is not None else None
        if local is None:
            return  # already matched or already timed out - nothing left to cancel
        local.timeout_task.cancel()
        await self._redis.zrem(self._seekers_queue_key, username)
        await ws.send(serialize_message(SeekCancelledMessage()))

    async def _claim_opponent_within_elo_range(self, rating: int) -> Optional[str]:
        """Atomically claims a waiting opponent within
        protocol.MATCHMAKING_ELO_RANGE of rating, or None if no one is
        currently queued in range. The range query (ZRANGEBYSCORE) and
        the claim (ZREM) are two separate awaited Redis round-trips, so
        a concurrent seeker could see the same candidate before either
        of us removes them - ZREM's return value (1 if it actually
        removed something, 0 if someone else already did) tells us
        whether we actually won that race; on a loss, look again rather
        than assume the candidate we saw is still free."""
        while True:
            candidates = await self._redis.zrangebyscore(
                self._seekers_queue_key,
                rating - protocol.MATCHMAKING_ELO_RANGE,
                rating + protocol.MATCHMAKING_ELO_RANGE,
            )
            if not candidates:
                return None
            candidate = candidates[0]
            if await self._redis.zrem(self._seekers_queue_key, candidate):
                return candidate

    def _username_of(self, ws: ServerConnection) -> Optional[str]:
        return next((u for u, connection in self._active_connections.items() if connection is ws), None)

    async def _create_room(self, ws: ServerConnection, message: CreateRoomMessage) -> None:
        username = self._username_of(ws)
        if username is None:
            return
        try:
            room = await self._room_registry.create(username, message.room_id)
        except RoomError as error:
            await ws.send(serialize_message(CreateRoomFailedMessage(reason=str(error))))
            return
        self._pending_room_creators[ws] = room.room_id
        logger.info("room %s created by %s", room.room_id, username)
        await ws.send(serialize_message(RoomCreatedMessage(room_id=room.room_id)))

    async def _join_room(self, ws: ServerConnection, message: JoinRoomMessage) -> None:
        username = self._username_of(ws)
        if username is None:
            return
        try:
            room = await self._room_registry.join(message.room_id, username)
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

    async def _cancel_room(self, ws: ServerConnection, message: CancelRoomMessage) -> None:
        username = self._username_of(ws)
        if username is None:
            return
        try:
            await self._room_registry.cancel(username)
        except RoomError as error:
            # race: an opponent just joined - MatchFoundMessage is already on its way instead
            logger.info("cancel room race for %s: %s", username, error)
            return
        self._pending_room_creators.pop(ws, None)
        logger.info("room cancelled by %s", username)
        await ws.send(serialize_message(RoomCancelledMessage()))

    async def _close_room(self, room_id: str) -> None:
        await self._room_registry.close(room_id)
        self._room_games.pop(room_id, None)

    async def on_disconnect(self, ws: ServerConnection) -> None:
        username = self._username_of(ws)
        if username is not None:
            del self._active_connections[username]

        local = self._waiting.pop(username, None) if username is not None else None
        if local is not None:
            local.timeout_task.cancel()
            await self._redis.zrem(self._seekers_queue_key, username)
            return

        pending_room_id = self._pending_room_creators.pop(ws, None)
        if pending_room_id is not None:
            # The creator vanished before anyone joined - just free the id,
            # there's no GameRoom or opponent to notify yet.
            logger.info("room %s abandoned (creator %s disconnected before anyone joined)", pending_room_id, username)
            await self._room_registry.close(pending_room_id)
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

        if room.is_game_over():
            # The game already ended before this connection dropped -
            # equivalent to closing the window instead of clicking
            # "Back to Lobby" (see _leave_room). No reconnect/auto-resign
            # grace period applies to a game that's already decided;
            # the opponent has no one left to rematch with either.
            for other_ws in await room.leave(ws):
                self._rooms.pop(other_ws, None)
                await self._safe_send(other_ws, LeftRoomMessage())
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

    async def _timeout_waiting(self, username: str) -> None:
        await asyncio.sleep(protocol.MATCHMAKING_TIMEOUT_SECONDS)
        local = self._waiting.pop(username, None)
        if local is None:
            return  # already matched or already disconnected
        await self._redis.zrem(self._seekers_queue_key, username)
        await local.ws.send(serialize_message(NoOpponentFoundMessage()))

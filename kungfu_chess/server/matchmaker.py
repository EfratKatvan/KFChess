from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional, Tuple, Type

from redis.asyncio import Redis
from websockets.asyncio.server import ServerConnection

from kungfu_chess.model.piece import BLACK, WHITE
from kungfu_chess.server import protocol, shard_protocol
from kungfu_chess.server.accounts_client import AccountsClient
from kungfu_chess.server.accounts_client import get_client as get_accounts_client
from kungfu_chess.server.auth_token import TokenClaims
from kungfu_chess.server.messages import (
    CancelRoomMessage,
    CancelSeekMessage,
    CreateRoomFailedMessage,
    CreateRoomMessage,
    JoinRoomFailedMessage,
    JoinRoomMessage,
    LoggedOutMessage,
    LoginFailedMessage,
    LogoutMessage,
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
    White, second = Black.

    Server_Design.md Stage 4a: this class no longer hosts a GameRoom
    itself - that lives in a separate game_shard.py process. A match
    (or a Room-dialog opponent seat, or a spectator join) is signaled
    to the caller via on_enter_relay, which the WS Gateway uses to
    open a relay connection to the Shard for that seat (see
    ws_gateway.py) - this class only ever fires that signal, it never
    waits to learn whether the Shard-side session actually succeeds
    (see on_connect's reconnect branch, and on_leave_relay below).

    Also routes reconnections: if a username that just disconnected
    mid-game logs back in within the room's grace period, it's routed
    back toward that same room/color instead of landing in the lobby.

    A username can only ever have one *live* connection at a time - a
    second simultaneous login (before the first disconnects) is
    rejected outright, rather than silently entering the lobby and
    potentially seeking against itself."""

    def __init__(
        self,
        accounts_client: Optional[AccountsClient] = None,
        redis_client: Optional[Redis] = None,
        on_enter_relay: Optional[Callable[[ServerConnection, shard_protocol.RoutingMessage], None]] = None,
        namespace: Optional[str] = None,
    ) -> None:
        self._accounts_client = accounts_client or get_accounts_client()
        self._redis = redis_client or get_redis_client()
        # Fired, never awaited - Matchmaker doesn't know or care who's
        # listening (the WS Gateway, in production), the same
        # publisher-doesn't-know-the-subscriber shape events/bus.py
        # already uses (Server_Design.md section 0). Defaults to a
        # no-op so every existing test that doesn't care about relay
        # routing keeps constructing a Matchmaker exactly as before.
        self._on_enter_relay = on_enter_relay or (lambda ws, routing: None)
        # A per-instance namespace, not a fixed key by default: production
        # now passes one explicitly (must match the Shard's own
        # RoomRegistry/GameAllocator namespace - see game_shard.py), but
        # every existing test that omits it gets the old per-instance
        # random isolation unchanged.
        self._namespace = namespace if namespace is not None else uuid.uuid4().hex
        self._seekers_queue_key = f"seekers:queue:{self._namespace}"
        self._waiting: Dict[str, _WaitingLocal] = {}  # username -> its local (non-Redis) bookkeeping
        # ws -> (room_id, color) once matched/joined - color is None for a
        # spectator. Replaces the old ws -> GameRoom map now that the room
        # itself lives in a different process (Stage 4a) - just enough to
        # route a reconnect or record a mid-game disconnect.
        self._room_of: Dict[ServerConnection, Tuple[str, Optional[str]]] = {}
        self._disconnected_players: Dict[str, Tuple[str, str]] = {}  # username -> (room_id, color)
        self._active_connections: Dict[str, ServerConnection] = {}  # username -> its one live connection
        self._token_of: Dict[ServerConnection, TokenClaims] = {}  # ws -> its session's verified token claims (Stage 1b)

        # The Room dialog's Create/Join/Cancel flow - independent of, and
        # parallel to, the ELO-proximity _waiting queue above. Shares this
        # Matchmaker's Redis client and per-instance namespace, same as
        # the seekers queue - and the same namespace the Shard's own
        # second RoomRegistry instance must be constructed with.
        self._room_registry = RoomRegistry(redis_client=self._redis, namespace=self._namespace)
        self._pending_room_creators: Dict[ServerConnection, str] = {}  # ws -> room_id, only while no opponent has joined yet

        # Dispatch table for lobby messages - one handler per message
        # kind, in place of a growing if/elif isinstance chain. Once a
        # connection enters relay mode (Stage 4a), its traffic never
        # reaches on_message/this table again until it's back in the
        # lobby (see on_leave_relay).
        self._lobby_handlers: Dict[Type[object], Callable[[ServerConnection, object], Awaitable[None]]] = {
            SeekGameMessage: self._start_seeking,
            CancelSeekMessage: self._cancel_seeking,
            CreateRoomMessage: self._create_room,
            JoinRoomMessage: self._join_room,
            CancelRoomMessage: self._cancel_room,
            LogoutMessage: self._handle_logout,
        }

    async def on_connect(
        self, ws: ServerConnection, username: str, claims: Optional[TokenClaims] = None
    ) -> bool:
        """Returns False (and sends LoginFailedMessage itself) if this
        username already has a live connection elsewhere - the caller
        should close the socket without entering the lobby/message
        handling for it. Otherwise always returns True - if this is a
        reconnect, whether the Shard actually accepts it (grace period
        not yet expired) is discovered later, once the relay session
        the caller opens resolves; a rejected one lands back in the
        lobby exactly like a fresh login (see on_leave_relay).

        `claims` (Stage 1b) is this connection's verified session token,
        tracked so a later LogoutMessage knows exactly which token to
        revoke - defaults to None so every existing test that doesn't
        care about logout/tokens keeps constructing calls unchanged."""
        if username in self._active_connections:
            await ws.send(serialize_message(
                LoginFailedMessage(reason="this account is already connected from another window")
            ))
            return False
        self._active_connections[username] = ws
        if claims is not None:
            self._token_of[ws] = claims

        pending = self._disconnected_players.pop(username, None)
        if pending is not None:
            room_id, color = pending
            self._room_of[ws] = (room_id, color)
            self._on_enter_relay(ws, shard_protocol.ReconnectMessage(room_id=room_id, color=color, username=username))
            logger.info("%s attempting to reconnect as %s to room %s", username, color, room_id)

        return True

    async def on_leave_relay(self, ws: ServerConnection) -> None:
        """Called by the caller (the WS Gateway) once a relay session
        ends *without* the underlying connection itself closing - a
        rejected reconnect/spectate, or an ordinary "Back to Lobby"
        after game-over (Stage 4a: game_shard.py's GameRoom.leave
        closes the relay socket for exactly this purpose). Clears the
        room-membership bookkeeping so a later on_disconnect treats
        this connection as an ordinary lobby disconnect, not a
        mid-game one."""
        self._room_of.pop(ws, None)

    async def on_message(self, ws: ServerConnection, raw: str) -> None:
        try:
            message = deserialize_message(raw)
        except (ValueError, KeyError, TypeError) as error:
            logger.warning("dropping malformed message from %s: %s", self._username_of(ws), error)
            return  # malformed/unrecognized lobby message - ignore, don't crash the connection
        handler = self._lobby_handlers.get(type(message))
        if handler is not None:
            await handler(ws, message)

    async def _start_seeking(self, ws: ServerConnection, message: SeekGameMessage) -> None:
        username = self._username_of(ws)
        if username is None or username in self._waiting:
            return  # not logged in, or a second Play click while waiting - both no-ops
        # Fetched fresh rather than cached from login, since a player who
        # has already finished one or more games this session has a
        # rating that's since moved in the database - a stale snapshot
        # could approve (or refuse) a match that no longer reflects
        # either player's real current rating.
        rating = await self._accounts_client.get_rating(username)

        timeout_task = asyncio.create_task(self._timeout_waiting(username))
        self._waiting[username] = _WaitingLocal(ws=ws, timeout_task=timeout_task)
        # Joins the shared queue *before* checking for an opponent - not
        # after. Two genuinely concurrent seekers (real, separate
        # connections - a single in-process test driving both seeks
        # sequentially never exposed this) could otherwise both check the
        # queue in the narrow window before either has actually joined
        # it, both conclude "no one's here in range," and both end up
        # waiting instead of matched with each other.
        await self._redis.zadd(self._seekers_queue_key, {username: rating})

        opponent_username = await self._claim_opponent_within_elo_range(rating, exclude=username)
        if opponent_username is not None:
            timeout_task.cancel()
            del self._waiting[username]
            await self._redis.zrem(self._seekers_queue_key, username)  # not staying queued after all
            opponent = self._waiting.pop(opponent_username, None)
            if opponent is not None:
                opponent.timeout_task.cancel()
                room_id = uuid.uuid4().hex
                self._room_of[opponent.ws] = (room_id, WHITE)
                self._room_of[ws] = (room_id, BLACK)
                self._on_enter_relay(opponent.ws, shard_protocol.HostSeatMessage(
                    room_id=room_id, color=WHITE, username=opponent_username, opponent_username=username,
                ))
                self._on_enter_relay(ws, shard_protocol.HostSeatMessage(
                    room_id=room_id, color=BLACK, username=username, opponent_username=opponent_username,
                ))
                logger.info("matched %s (white) vs %s (black)", opponent_username, username)
                return
            # Claimed them in the Redis queue, but they're already gone
            # from local bookkeeping (disconnected/cancelled in the
            # narrow window between the two) - either way they're no
            # longer queued, so re-join the queue as an ordinary
            # unmatched seeker instead.
            logger.info("claimed opponent %s but they'd already left - %s stays unmatched", opponent_username, username)
            timeout_task = asyncio.create_task(self._timeout_waiting(username))
            self._waiting[username] = _WaitingLocal(ws=ws, timeout_task=timeout_task)
            await self._redis.zadd(self._seekers_queue_key, {username: rating})

        await ws.send(serialize_message(WaitingForOpponentMessage()))

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

    async def _claim_opponent_within_elo_range(self, rating: int, exclude: str) -> Optional[str]:
        """Atomically claims a waiting opponent within
        protocol.MATCHMAKING_ELO_RANGE of rating, or None if no one else
        is currently queued in range. `exclude` is the calling seeker's
        own username - now already in the queue itself by the time this
        runs (see _start_seeking), so it must never claim itself as its
        own opponent. The range query (ZRANGEBYSCORE) and the claim
        (ZREM) are two separate awaited Redis round-trips, so a
        concurrent seeker could see the same candidate before either of
        us removes them - ZREM's return value (1 if it actually removed
        something, 0 if someone else already did) tells us whether we
        actually won that race; on a loss, look again rather than assume
        the candidate we saw is still free."""
        while True:
            candidates = await self._redis.zrangebyscore(
                self._seekers_queue_key,
                rating - protocol.MATCHMAKING_ELO_RANGE,
                rating + protocol.MATCHMAKING_ELO_RANGE,
            )
            candidates = [candidate for candidate in candidates if candidate != exclude]
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
            self._room_of[creator_ws] = (room.room_id, WHITE)
            self._room_of[ws] = (room.room_id, BLACK)
            self._on_enter_relay(creator_ws, shard_protocol.HostSeatMessage(
                room_id=room.room_id, color=WHITE, username=room.creator_username, opponent_username=username,
            ))
            self._on_enter_relay(ws, shard_protocol.HostSeatMessage(
                room_id=room.room_id, color=BLACK, username=username, opponent_username=room.creator_username,
            ))
            logger.info("room %s: %s joined as black - game starting", room.room_id, username)
            return

        # The room already had an opponent - this join is a spectator.
        # on_enter_relay fires last, deliberately: it's the current
        # connection's own ws, and firing it before this handler's own
        # remaining awaits (the rating lookups, the direct send below)
        # would let the Gateway's mode-switching loop (ws_gateway.py)
        # race ahead and cancel this coroutine mid-flight the instant
        # the relay request lands in its queue - same reasoning as
        # _start_seeking/_join_room's opponent-seat branch, which
        # already fire the current connection's own relay request last.
        self._room_of[ws] = (room.room_id, None)
        logger.info("room %s: %s joined as a spectator", room.room_id, username)
        white_rating = await self._accounts_client.get_rating(room.creator_username)
        black_rating = await self._accounts_client.get_rating(room.opponent_username)
        await ws.send(serialize_message(SpectatingMessage(
            room_id=room.room_id,
            white_username=room.creator_username,
            white_rating=white_rating,
            black_username=room.opponent_username,
            black_rating=black_rating,
        )))
        self._on_enter_relay(ws, shard_protocol.SpectateMessage(room_id=room.room_id, username=username))

    async def _cancel_room(self, ws: ServerConnection, message: CancelRoomMessage) -> None:
        username = self._username_of(ws)
        if username is None:
            return
        try:
            await self._room_registry.cancel(username)
        except RoomError as error:
            # race: an opponent just joined - a HostSeatMessage relay is already on its way instead
            logger.info("cancel room race for %s: %s", username, error)
            return
        self._pending_room_creators.pop(ws, None)
        logger.info("room cancelled by %s", username)
        await ws.send(serialize_message(RoomCancelledMessage()))

    async def _handle_logout(self, ws: ServerConnection, message: LogoutMessage) -> None:
        """The lobby's "Logout" button (Stage 1b, Server_Design.md
        section 1.1): revokes this connection's session token - a
        Redis key per jti with a TTL equal to the token's own remaining
        lifetime (never longer - a revoked entry can't outlive what the
        token would have expired to on its own anyway), so a later
        TokenLoginMessage with the same token is rejected fleet-wide,
        not just on this one Gateway. Then closes the connection with a
        normal close code - the client re-enters the login screen once
        it processes LoggedOutMessage, and this same username can log
        back in immediately since _active_connections is freed exactly
        the same way any other disconnect frees it (see on_disconnect)."""
        claims = self._token_of.pop(ws, None)
        if claims is not None:
            remaining_seconds = max(1, claims.expires_at - int(time.time()))
            await self._redis.set(f"revoked:token:{claims.jti}", "1", ex=remaining_seconds)
        await ws.send(serialize_message(LoggedOutMessage()))
        await ws.close()

    async def on_disconnect(self, ws: ServerConnection) -> None:
        username = self._username_of(ws)
        if username is not None:
            del self._active_connections[username]
        self._token_of.pop(ws, None)

        local = self._waiting.pop(username, None) if username is not None else None
        if local is not None:
            local.timeout_task.cancel()
            await self._redis.zrem(self._seekers_queue_key, username)
            return

        pending_room_id = self._pending_room_creators.pop(ws, None)
        if pending_room_id is not None:
            # The creator vanished before anyone joined - just free the id,
            # there's no room or opponent to notify yet.
            logger.info("room %s abandoned (creator %s disconnected before anyone joined)", pending_room_id, username)
            await self._room_registry.close(pending_room_id)
            return

        membership = self._room_of.pop(ws, None)
        if membership is None:
            return  # was in the lobby (or its relay session already ended - see on_leave_relay), nothing to do
        room_id, color = membership
        if color is None:
            logger.info("%s left as a spectator", username)
            return

        # Whether this was genuinely mid-game (vs. the game having already
        # ended a moment before the socket dropped) is no longer decided
        # here - the Shard has the live GameRoom and decides that itself
        # (game_shard.py's _run_seat_messages). A reconnect attempt for an
        # already-finished/released room simply finds no room Shard-side
        # and falls back to the lobby, the same end result either way.
        logger.info("%s disconnected (room %s)", username, room_id)
        self._disconnected_players[username] = (room_id, color)
        asyncio.create_task(self._forget_if_still_pending(username, (room_id, color)))

    async def _forget_if_still_pending(self, username: str, membership: Tuple[str, str]) -> None:
        """Cleans up the reconnect-routing entry once the grace period
        (plus a small buffer) has passed - if the player never came
        back, the Shard has already auto-resigned by then, so this
        entry would otherwise just linger forever pointing at a
        finished game."""
        await asyncio.sleep(protocol.DISCONNECT_GRACE_SECONDS + 1)
        pending = self._disconnected_players.get(username)
        if pending is not None and pending == membership:
            del self._disconnected_players[username]

    async def _timeout_waiting(self, username: str) -> None:
        await asyncio.sleep(protocol.MATCHMAKING_TIMEOUT_SECONDS)
        local = self._waiting.pop(username, None)
        if local is None:
            return  # already matched or already disconnected
        await self._redis.zrem(self._seekers_queue_key, username)
        await local.ws.send(serialize_message(NoOpponentFoundMessage()))

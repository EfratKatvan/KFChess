from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict
from typing import Any, Awaitable, Callable, Dict, Optional, Type

from prometheus_client import Counter, Gauge
from redis.asyncio import Redis
from websockets.asyncio.server import ServerConnection

from kungfu_chess.model.piece import BLACK, WHITE
from kungfu_chess.server import protocol, shard_protocol
from kungfu_chess.server.accounts_client import AccountsClient
from kungfu_chess.server.accounts_client import get_client as get_accounts_client
from kungfu_chess.server.agones_allocation_client import AgonesAllocationClient
from kungfu_chess.server.auth_token import TokenClaims
from kungfu_chess.server.matchmaker_leader import MatchmakerLeaderElection
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
from kungfu_chess.server.room_shard_registry import RoomShardRegistry
from kungfu_chess.server.rooms import RoomError, RoomRegistry
from kungfu_chess.server.serialization import deserialize_message, serialize_message

logger = logging.getLogger(__name__)

# Server_Design.md section 1: this role's own named scaling metric is
# queue depth. A plain inc()/dec() pair (not set_function, which can't
# call the async Redis round trip a true live count would now need) -
# each replica's own delta, summed across replicas by Prometheus's own
# sum() at query time, is the standard, correct pattern for a gauge
# that's genuinely shared state now, not one replica's private dict.
SEEKERS_WAITING = Gauge("matchmaking_seekers_waiting", "Players currently waiting for an ELO match")
MATCHES_MADE_TOTAL = Counter("matchmaking_matches_made_total", "Total ELO matches made")
ROOMS_CREATED_TOTAL = Counter("matchmaking_rooms_created_total", "Total Create Room rooms created")


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
        on_enter_relay: Optional[Callable[[str, shard_protocol.RoutingMessage], None]] = None,
        namespace: Optional[str] = None,
        leader_election: Optional[MatchmakerLeaderElection] = None,
        remote_connection_resolver: Optional[Callable[[str], Any]] = None,
        agones_allocator: Optional[AgonesAllocationClient] = None,
    ) -> None:
        self._accounts_client = accounts_client or get_accounts_client()
        self._redis = redis_client or get_redis_client()
        # Server_Design.md section 3 (Stage 7): None by default, so
        # every existing test/docker-compose keeps constructing a
        # Matchmaker exactly as before, with brand-new rooms placed
        # exactly as they always were (whichever replica Kubernetes'
        # own Service load-balancing sends a HostSeatMessage to -
        # ws_gateway.py's _resolve_shard_address falls back to the
        # fixed shard_host/shard_port whenever this key was never
        # written). Only matchmaking_service.py's production wiring
        # passes a real one.
        self._agones_allocator = agones_allocator
        # Fired, never awaited - Matchmaker doesn't know or care who's
        # listening (the Matchmaking Service's Redis-publish adapter, in
        # production), the same publisher-doesn't-know-the-subscriber
        # shape events/bus.py already uses (Server_Design.md section 0).
        # Takes a connection_id (a plain string), not a live connection -
        # since Stage 5b/this stage, the *other* side of a match may be
        # held by a *different* Matchmaking Service replica than the one
        # that just decided it (see run_matching_tick), so there is no
        # live object to hand over, only an id whoever holds that
        # connection can resolve for themselves. Defaults to a no-op so
        # every existing test that doesn't care about relay routing keeps
        # constructing a Matchmaker exactly as before.
        self._on_enter_relay = on_enter_relay or (lambda connection_id, routing: None)
        # A per-instance namespace, not a fixed key by default: production
        # now passes one explicitly (must match the Shard's own
        # RoomRegistry/GameAllocator namespace - see game_shard.py), but
        # every existing test that omits it gets the old per-instance
        # random isolation unchanged.
        self._namespace = namespace if namespace is not None else uuid.uuid4().hex
        # Same namespace/Redis as game_shard.py's own RoomShardRegistry -
        # written here, at allocation time (see _allocate_shard_for),
        # before either seat's HostSeatMessage is sent; read by
        # ws_gateway.py's _resolve_shard_address for every routing
        # message, HostSeatMessage included now (Server_Design.md
        # section 3, Stage 7).
        self._room_shard_registry = RoomShardRegistry(self._redis, self._namespace)
        self._seekers_queue_key = f"seekers:queue:{self._namespace}"
        # Every waiting seeker's (connection_id, enqueued_at) - a Redis
        # Hash, not a local dict (Server_Design.md section 1: this is
        # exactly the state that has to be genuinely shared for
        # queue-depth scaling to be *safe*, not just nominal - a seeker
        # connected through one Matchmaking Service replica must still be
        # matchable by whichever replica's run_matching_tick happens to be
        # leader at the time). The rating itself still lives only as the
        # seekers-queue ZSET's own score - not duplicated here either.
        self._seekers_meta_key = f"seekers:meta:{self._namespace}"
        # connection_id -> the actual live object *this* replica can call
        # .send()/.close() on - every connection this replica itself
        # holds, regardless of what it's doing (seeking, in a room,
        # spectating). The tick's own resolver falls back to
        # remote_connection_resolver for a connection_id held by some
        # *other* replica - see _resolve().
        self._connection_by_id: Dict[str, Any] = {}
        self._leader_election = leader_election
        self._remote_connection_resolver = remote_connection_resolver

        # Every one of the keys below replaces what used to be a plain
        # dict keyed by a live `ws` object - correct only as long as
        # every request for a given connection was guaranteed to land
        # back on the exact same Matchmaker instance. Once Matchmaker
        # moved into its own network service (matchmaking_service.py),
        # that guarantee no longer holds: a Kubernetes Service in front
        # of several replicas gives no session affinity, so a login's
        # /connect call and a later /message (Seek, Cancel, Create Room,
        # ...) or /disconnect for the *same* connection_id can each land
        # on a *different* replica. Keying by connection_id in Redis
        # instead - not by the ws object itself, which only this
        # replica can hold - is what makes that safe: any replica can
        # look up (and act on) any connection's state, the same
        # property the seekers queue above already had.
        #
        # Deliberately not solved here: a replica (chiefly the WS
        # Gateway, which owns the real client socket) that crashes
        # without ever calling /disconnect leaves its username's entry
        # in _active_by_username_key stale forever, permanently
        # refusing that username's next login. The in-memory version
        # had the opposite failure mode by accident (a crashed process
        # silently dropped its own state) rather than by design - a
        # real fix needs a heartbeat/liveness TTL on top of this, which
        # is a separate feature, not bundled into this fix.
        self._active_by_username_key = f"active_by_username:{self._namespace}"  # username -> connection_id
        self._active_usernames_key = f"active_usernames:{self._namespace}"  # connection_id -> username
        self._room_of_key = f"room_of:{self._namespace}"  # connection_id -> json({room_id, color})
        self._token_of_key = f"token_of:{self._namespace}"  # connection_id -> json(TokenClaims)
        self._disconnected_key_prefix = f"disconnected:{self._namespace}:"  # +username -> json({room_id, color}), self-expiring

        # The Room dialog's Create/Join/Cancel flow - independent of, and
        # parallel to, the ELO-proximity seekers queue above. Shares this
        # Matchmaker's Redis client and per-instance namespace, same as
        # the seekers queue - and the same namespace the Shard's own
        # second RoomRegistry instance must be constructed with. Already
        # fully Redis-backed (rooms.py) - RoomRegistry.room_for_username
        # plus Room.is_pending is enough to tell a creator-abandoned-
        # before-anyone-joined disconnect apart from any other kind (see
        # on_disconnect), so no separate _pending_room_creators map is
        # needed here at all.
        self._room_registry = RoomRegistry(redis_client=self._redis, namespace=self._namespace)

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

    async def _resolve(self, connection_id: str) -> Optional[Any]:
        """A connection this replica itself holds resolves directly;
        one held by a different replica falls back to
        remote_connection_resolver (production: reconstructs a
        matchmaking_service.py _RemoteConnection from the bare id,
        which needs nothing else to publish to it - see that module's
        own docstring on why that's enough). None if neither resolves
        it (the tests that never wire a remote resolver, driving only
        connections they themselves constructed)."""
        ws = self._connection_by_id.get(connection_id)
        if ws is not None:
            return ws
        if self._remote_connection_resolver is not None:
            return self._remote_connection_resolver(connection_id)
        return None

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
        # HSETNX: an atomic check-and-set - two /connect calls for the
        # same username racing across two replicas can never both win,
        # unlike the plain "in dict" check this replaced, which was only
        # ever safe because there was just one replica to race on.
        accepted = await self._redis.hsetnx(self._active_by_username_key, username, ws.connection_id)
        if not accepted:
            await ws.send(serialize_message(
                LoginFailedMessage(reason="this account is already connected from another window")
            ))
            return False
        await self._redis.hset(self._active_usernames_key, ws.connection_id, username)
        self._connection_by_id[ws.connection_id] = ws
        if claims is not None:
            await self._redis.hset(self._token_of_key, ws.connection_id, json.dumps(asdict(claims)))

        pending_raw = await self._redis.getdel(f"{self._disconnected_key_prefix}{username}")
        if pending_raw is not None:
            pending = json.loads(pending_raw)
            room_id, color = pending["room_id"], pending["color"]
            await self._redis.hset(self._room_of_key, ws.connection_id, json.dumps({"room_id": room_id, "color": color}))
            self._on_enter_relay(
                ws.connection_id, shard_protocol.ReconnectMessage(room_id=room_id, color=color, username=username)
            )
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
        await self._redis.hdel(self._room_of_key, ws.connection_id)

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
        """Enqueues only - never pairs inline (Server_Design.md section
        1: unlike Stage 3's single-instance version, a request landing
        on any one Matchmaking Service replica can no longer assume it's
        the only one looking at the queue). The actual pairing decision
        happens in run_matching_tick, on whichever replica currently
        holds the leader lease - see that method's own docstring for
        why splitting these two concerns is what makes "many replicas
        accepting Play clicks, one replica deciding who's paired"
        actually safe."""
        username = await self._username_of(ws)
        if username is None or await self._redis.hexists(self._seekers_meta_key, username):
            return  # not logged in, or a second Play click while waiting - both no-ops
        # Fetched fresh rather than cached from login, since a player who
        # has already finished one or more games this session has a
        # rating that's since moved in the database - a stale snapshot
        # could approve (or refuse) a match that no longer reflects
        # either player's real current rating.
        rating = await self._accounts_client.get_rating(username)

        meta = json.dumps({"connection_id": ws.connection_id, "enqueued_at": time.time(), "region": message.region})
        await self._redis.hset(self._seekers_meta_key, username, meta)
        await self._redis.zadd(self._seekers_queue_key, {username: rating})
        SEEKERS_WAITING.inc()
        await ws.send(serialize_message(WaitingForOpponentMessage()))

    async def _cancel_seeking(self, ws: ServerConnection, message: CancelSeekMessage) -> None:
        """The Back button on the "Waiting for opponent..." screen - the
        Play-button counterpart to _cancel_room. ZREM's return value (1
        if it actually removed something) tells us whether this seeker
        was still queued - run_matching_tick could have claimed them for
        a match in the narrow window before this call, in which case
        there is nothing left to cancel."""
        username = await self._username_of(ws)
        if username is None:
            return
        removed = await self._redis.zrem(self._seekers_queue_key, username)
        await self._redis.hdel(self._seekers_meta_key, username)
        if not removed:
            return  # already matched (or already timed out) - nothing left to cancel
        SEEKERS_WAITING.dec()
        await ws.send(serialize_message(SeekCancelledMessage()))

    async def run_matching_tick(self) -> None:
        """The only place ELO pairing actually happens now. Called
        periodically by whoever owns this Matchmaker
        (matchmaking_service.py's own tick loop in production; a test
        calls it directly, once, right after the seeks it wants paired).

        A no-op if leader_election is set and this instance isn't
        currently the leader. If leader_election is None (every
        existing test, and this class's own single-instance default),
        this instance always acts as sole decision-maker - Stage 3's
        original assumption, unchanged for anyone who doesn't opt into
        the multi-replica machinery.

        Splitting "accept a seek" (any replica) from "decide a match"
        (the leader alone, here) is what actually fixes the race Stage
        5b's own Matchmaking Service extraction left open: the seekers
        queue itself was already Redis-shared (section 16.1), but
        *deciding* two people are paired, and notifying them, must only
        ever happen once - not once per replica that happens to be
        looking at the queue at the same moment. Every waiting seeker's
        connection_id is resolved via _resolve(), which works whether
        that connection is local to this replica or not - see
        run_matching_tick's own callers for how a non-local one gets
        wired up (matchmaking_service.py's own remote_connection_resolver).

        Documented gap this does *not* close: if the leader is a
        *different* replica from either matched player's own connection,
        that connection's own replica never learns the resulting room_id/
        color (_room_of stays local, deliberately - see __init__'s own
        comment), so a later disconnect on that replica won't route a
        reconnect. Fixing that needs _room_of itself to become
        Redis-shared, a separate, larger change - not bundled into this
        one, which fixes the pairing race actually observed and tested."""
        if self._leader_election is not None:
            if not await self._leader_election.try_become_leader():
                return
        await self._sweep_timed_out_seekers()
        await self._sweep_matches()

    async def _sweep_timed_out_seekers(self) -> None:
        now = time.time()
        for username in await self._redis.zrange(self._seekers_queue_key, 0, -1):
            raw_meta = await self._redis.hget(self._seekers_meta_key, username)
            if raw_meta is None:
                continue  # a match claimed them between the zrange snapshot and this read
            meta = json.loads(raw_meta)
            if now - meta["enqueued_at"] < protocol.MATCHMAKING_TIMEOUT_SECONDS:
                continue
            if not await self._redis.zrem(self._seekers_queue_key, username):
                continue  # a match claimed them in the same narrow window - let that stand
            await self._redis.hdel(self._seekers_meta_key, username)
            SEEKERS_WAITING.dec()
            ws = await self._resolve(meta["connection_id"])
            if ws is not None:
                await ws.send(serialize_message(NoOpponentFoundMessage()))

    async def _pair_within(self, entries: list) -> list:
        """The linear-scan-adjacent-pairing algorithm itself, unchanged
        from before region-awareness (Server_Design.md section 7) - now
        called on a subset (one region group, or the cross-region
        leftovers) instead of always the whole queue. `entries` must
        already be rating-sorted. ZREM'ing both sides of a pair
        atomically (one round trip, both-or-neither in effect since a
        partial removal is treated as "someone else already touched
        this pair" and simply retried next tick) is what keeps two
        ticks (only possible if leader_election is None and something
        is calling this concurrently with itself, which nothing in this
        codebase does) from both believing they matched the same
        person. Returns whatever this pass couldn't pair."""
        i = 0
        while i < len(entries) - 1:
            username_a, rating_a = entries[i]
            username_b, rating_b = entries[i + 1]
            if rating_b - rating_a > protocol.MATCHMAKING_ELO_RANGE:
                i += 1
                continue
            removed = await self._redis.zrem(self._seekers_queue_key, username_a, username_b)
            if removed != 2:
                i += 1
                continue
            await self._pair(username_a, username_b)
            entries = entries[i + 2:]
            i = 0
        return entries

    async def _sweep_matches(self) -> None:
        """Ratings sort the same seekers queue ZSET already keys by
        (section 16.1) - so two seekers within
        protocol.MATCHMAKING_ELO_RANGE of each other are always
        *adjacent* once sorted, and _pair_within's linear scan finds
        every pairable pair in one pass, no per-seeker range query
        needed.

        Region-aware (Server_Design.md section 7, Stage 7): the
        rating-sorted queue is first partitioned by each seeker's own
        region (order-preserving, so every group stays rating-sorted on
        its own) and _pair_within runs once per group - same-region
        bias. Whatever's left unpaired across every group is combined,
        re-sorted by rating (a per-group leftover list isn't globally
        rating-ordered relative to a *different* group's leftovers),
        and _pair_within runs once more on that combined list - the
        cross-region fallback pass, using the exact same pairing
        algorithm, just on a different subset. A seeker whose region
        was never recorded (shouldn't happen - _start_seeking always
        writes one) falls back to protocol.DEFAULT_REGION's group
        rather than crashing this whole tick."""
        entries = await self._redis.zrange(self._seekers_queue_key, 0, -1, withscores=True)
        if not entries:
            return
        raw_meta_by_username = await self._redis.hgetall(self._seekers_meta_key)

        def _region_of(username: str) -> str:
            raw = raw_meta_by_username.get(username)
            if raw is None:
                return protocol.DEFAULT_REGION
            return json.loads(raw).get("region", protocol.DEFAULT_REGION)

        groups: Dict[str, list] = {}
        for entry in entries:
            groups.setdefault(_region_of(entry[0]), []).append(entry)

        leftovers = []
        for group_entries in groups.values():
            leftovers.extend(await self._pair_within(group_entries))
        leftovers.sort(key=lambda entry: entry[1])
        await self._pair_within(leftovers)

    _REGION_FLEET_NAMES = {"il": "game-shard", protocol.DEFAULT_REGION: "game-shard", "eu": "game-shard-eu"}

    def _fleet_name_for_region(self, region: str) -> str:
        """Maps a matched room's decided region onto the Agones Fleet
        that simulates it (k8s/game-shard-fleet.yaml) - an unrecognized
        region (a future client sending something outside
        protocol.SUPPORTED_REGIONS) safely falls back to the default
        Fleet rather than failing allocation outright."""
        return self._REGION_FLEET_NAMES.get(region, "game-shard")

    async def _allocate_shard_for(self, room_id: str, fleet_name: str = "game-shard") -> bool:
        """Server_Design.md section 3 (Stage 7): the one choke point
        that decides which Game Shard replica hosts a brand-new room -
        called once per room, here, *before* either seat's
        HostSeatMessage is ever sent, so both seats' independent
        Gateway connections resolve the *same* replica afterward via
        room_shard_registry (see ws_gateway.py's own
        _resolve_shard_address, which now looks this up for every
        routing message, HostSeatMessage included). A no-op returning
        True when no agones_allocator is configured at all (every
        existing test/docker-compose) - placement then stays exactly
        what it always was: whichever replica Kubernetes' own Service
        happens to route each connection to."""
        if self._agones_allocator is None:
            return True
        shard_address = await self._agones_allocator.allocate(fleet_name)
        if shard_address is None:
            logger.warning("room %s: Agones allocation against fleet %s failed", room_id, fleet_name)
            return False
        await self._room_shard_registry.confirm_or_acquire(room_id, shard_address)
        return True

    async def _pair(self, white_username: str, black_username: str) -> None:
        raw_white_meta = await self._redis.hget(self._seekers_meta_key, white_username)
        raw_black_meta = await self._redis.hget(self._seekers_meta_key, black_username)
        await self._redis.hdel(self._seekers_meta_key, white_username, black_username)
        SEEKERS_WAITING.dec()
        SEEKERS_WAITING.dec()
        white_meta = json.loads(raw_white_meta)
        black_meta = json.loads(raw_black_meta)
        white_connection_id = white_meta["connection_id"]
        black_connection_id = black_meta["connection_id"]
        # Server_Design.md section 7: the room's region for Fleet
        # placement is white's own region - correct as-is for a
        # same-region match (both seekers share it by construction, see
        # _sweep_matches's own per-region grouping), and an arbitrary
        # but consistent choice for a cross-region fallback match,
        # mirroring this codebase's existing "creator/first seat is
        # always white" convention elsewhere.
        region = white_meta.get("region", protocol.DEFAULT_REGION)

        room_id = uuid.uuid4().hex
        if not await self._allocate_shard_for(room_id, fleet_name=self._fleet_name_for_region(region)):
            # Fleet at capacity, RBAC misconfigured, API unreachable -
            # tell both players plainly rather than silently vanishing
            # them mid-match, reusing the exact same message
            # _sweep_timed_out_seekers already sends on its own "we
            # tried, no luck" path (no new message type needed).
            for connection_id in (white_connection_id, black_connection_id):
                ws = await self._resolve(connection_id)
                if ws is not None:
                    await ws.send(serialize_message(NoOpponentFoundMessage()))
            return
        # Written by connection_id, unconditionally - not gated on
        # _resolve() finding a local ws (see __init__'s own note on why
        # this is now Redis-shared): the *other* replica actually
        # holding this connection needs to see this membership on its
        # own next on_disconnect, regardless of which replica is the
        # leader that decided this match.
        await self._redis.hset(self._room_of_key, white_connection_id, json.dumps({"room_id": room_id, "color": WHITE}))
        await self._redis.hset(self._room_of_key, black_connection_id, json.dumps({"room_id": room_id, "color": BLACK}))
        self._on_enter_relay(white_connection_id, shard_protocol.HostSeatMessage(
            room_id=room_id, color=WHITE, username=white_username, opponent_username=black_username,
        ))
        self._on_enter_relay(black_connection_id, shard_protocol.HostSeatMessage(
            room_id=room_id, color=BLACK, username=black_username, opponent_username=white_username,
        ))
        logger.info("matched %s (white) vs %s (black)", white_username, black_username)
        MATCHES_MADE_TOTAL.inc()

    async def _username_of(self, ws: ServerConnection) -> Optional[str]:
        return await self._redis.hget(self._active_usernames_key, ws.connection_id)

    async def _create_room(self, ws: ServerConnection, message: CreateRoomMessage) -> None:
        username = await self._username_of(ws)
        if username is None:
            return
        try:
            room = await self._room_registry.create(username, message.room_id)
        except RoomError as error:
            await ws.send(serialize_message(CreateRoomFailedMessage(reason=str(error))))
            return
        logger.info("room %s created by %s", room.room_id, username)
        ROOMS_CREATED_TOTAL.inc()
        await ws.send(serialize_message(RoomCreatedMessage(room_id=room.room_id)))

    async def _join_room(self, ws: ServerConnection, message: JoinRoomMessage) -> None:
        username = await self._username_of(ws)
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
            if not await self._allocate_shard_for(room.room_id):
                # Known, deliberately simple limitation for this stage
                # (Server_Design.md section 3): the room is already
                # marked full in RoomRegistry at this point, so a failed
                # allocation here leaves it unusable rather than
                # retryable - the same category of simple-not-silent
                # limitation _handle_host_seat's own pending-room timeout
                # already accepts elsewhere in this codebase.
                await ws.send(serialize_message(JoinRoomFailedMessage(reason="placement failed - try again")))
                return
            # Looked up by connection_id straight from Redis, not through
            # a local ws - the creator's own connection may belong to a
            # different replica than the one handling this join (see
            # __init__'s own note on why every per-connection map here
            # is now keyed by connection_id in Redis, not a live ws).
            creator_connection_id = await self._redis.hget(self._active_by_username_key, room.creator_username)
            await self._redis.hset(self._room_of_key, creator_connection_id, json.dumps({"room_id": room.room_id, "color": WHITE}))
            await self._redis.hset(self._room_of_key, ws.connection_id, json.dumps({"room_id": room.room_id, "color": BLACK}))
            self._on_enter_relay(creator_connection_id, shard_protocol.HostSeatMessage(
                room_id=room.room_id, color=WHITE, username=room.creator_username, opponent_username=username,
            ))
            self._on_enter_relay(ws.connection_id, shard_protocol.HostSeatMessage(
                room_id=room.room_id, color=BLACK, username=username, opponent_username=room.creator_username,
            ))
            logger.info("room %s: %s joined as black - game starting", room.room_id, username)
            MATCHES_MADE_TOTAL.inc()
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
        await self._redis.hset(self._room_of_key, ws.connection_id, json.dumps({"room_id": room.room_id, "color": None}))
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
        self._on_enter_relay(ws.connection_id, shard_protocol.SpectateMessage(room_id=room.room_id, username=username))

    async def _cancel_room(self, ws: ServerConnection, message: CancelRoomMessage) -> None:
        username = await self._username_of(ws)
        if username is None:
            return
        try:
            await self._room_registry.cancel(username)
        except RoomError as error:
            # race: an opponent just joined - a HostSeatMessage relay is already on its way instead
            logger.info("cancel room race for %s: %s", username, error)
            return
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
        back in immediately since _active_by_username_key is freed
        exactly the same way any other disconnect frees it (see
        on_disconnect)."""
        raw_claims = await self._redis.hget(self._token_of_key, ws.connection_id)
        await self._redis.hdel(self._token_of_key, ws.connection_id)
        if raw_claims is not None:
            claims = TokenClaims(**json.loads(raw_claims))
            remaining_seconds = max(1, claims.expires_at - int(time.time()))
            await self._redis.set(f"revoked:token:{claims.jti}", "1", ex=remaining_seconds)
        await ws.send(serialize_message(LoggedOutMessage()))
        await ws.close()

    async def on_disconnect(self, ws: ServerConnection) -> None:
        username = await self._username_of(ws)
        if username is not None:
            await self._redis.hdel(self._active_by_username_key, username)
        await self._redis.hdel(self._active_usernames_key, ws.connection_id)
        await self._redis.hdel(self._token_of_key, ws.connection_id)
        self._connection_by_id.pop(ws.connection_id, None)

        if username is not None:
            was_waiting = await self._redis.zrem(self._seekers_queue_key, username)
            await self._redis.hdel(self._seekers_meta_key, username)
            if was_waiting:
                SEEKERS_WAITING.dec()
                return

        if username is not None:
            room = await self._room_registry.room_for_username(username)
            if room is not None and room.is_pending and room.creator_username == username:
                # The creator vanished before anyone joined - just free
                # the room, there's no opponent to notify yet.
                logger.info("room %s abandoned (creator %s disconnected before anyone joined)", room.room_id, username)
                await self._room_registry.close(room.room_id)
                return

        raw_membership = await self._redis.hget(self._room_of_key, ws.connection_id)
        await self._redis.hdel(self._room_of_key, ws.connection_id)
        if raw_membership is None:
            return  # was in the lobby (or its relay session already ended - see on_leave_relay), nothing to do
        membership = json.loads(raw_membership)
        room_id, color = membership["room_id"], membership["color"]
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
        # A self-expiring Redis key, not a dict entry plus a background
        # asyncio task that outlives this replica's own memory of it
        # (the old _forget_if_still_pending) - correctly cleans itself
        # up after the grace period regardless of which replica (if
        # any) is still running by then, and regardless of which
        # replica's on_connect later reads it back via getdel.
        await self._redis.set(
            f"{self._disconnected_key_prefix}{username}",
            json.dumps({"room_id": room_id, "color": color}),
            ex=protocol.DISCONNECT_GRACE_SECONDS + 1,
        )

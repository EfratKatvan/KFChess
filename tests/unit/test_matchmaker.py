import asyncio
import json
from typing import Any, List, Optional, Tuple

from kungfu_chess.model.piece import WHITE, BLACK
from kungfu_chess.server import accounts, accounts_db, protocol, shard_protocol
from kungfu_chess.server.accounts_client import AccountsClient
from kungfu_chess.server.matchmaker import Matchmaker
from kungfu_chess.server.messages import (
    CancelRoomMessage,
    CancelSeekMessage,
    CreateRoomMessage,
    JoinRoomMessage,
    SeekGameMessage,
)
from kungfu_chess.server.serialization import serialize_message


class FakeConnection:
    """A stand-in for websockets.asyncio.server.ServerConnection - only
    needs an async send() that records what was sent, since Matchmaker
    (Stage 4a: never a live GameRoom - see game_shard.py) is the only
    thing that ever calls anything on a connection directly here.
    connection_id (this stage's own addition) reuses `name` as a
    convenient, already-unique-per-test stand-in - Matchmaker itself
    only ever needs it to be a stable string identifying this
    connection, the same role a real matchmaking_service.py
    _RemoteConnection's connection_id plays."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.connection_id = name
        self.sent = []

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


def _last_type(connection: FakeConnection):
    return connection.sent[-1]["type"] if connection.sent else None


class FakeRelayOpener:
    """Records every on_enter_relay call a Matchmaker under test fires -
    Stage 4a's replacement for reaching into a live GameRoom to check a
    match/join/reconnect/spectate actually happened, since Matchmaker
    itself never constructs one anymore (see game_shard.py). Whether the
    resulting relay session actually succeeds is exercised separately,
    against a real Shard, in test_relay_integration.py.

    Keyed by connection_id (a plain string, this stage's own change -
    see matchmaker.py's own on_enter_relay docstring for why) rather
    than a live connection object - last_for still accepts either a
    FakeConnection or a bare connection_id string, so every existing
    call site (`relay_opener.last_for(alice)`) keeps working unchanged."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, Any]] = []

    def __call__(self, connection_id: str, routing: shard_protocol.RoutingMessage) -> None:
        self.calls.append((connection_id, routing))

    def last_for(self, ws_or_connection_id) -> Optional[shard_protocol.RoutingMessage]:
        connection_id = getattr(ws_or_connection_id, "connection_id", ws_or_connection_id)
        return next((routing for cid, routing in reversed(self.calls) if cid == connection_id), None)


def _make_matchmaker(accounts_base_url: str, relay_opener: Optional[FakeRelayOpener] = None) -> Matchmaker:
    return Matchmaker(accounts_client=AccountsClient(accounts_base_url), on_enter_relay=relay_opener)


async def _connect(matchmaker: Matchmaker, db_path: str, ws: FakeConnection, username: str, rating: int) -> bool:
    """The test-side stand-in for a real login/register, which always
    creates the account's DB row before Matchmaker.on_connect is ever
    called - matchmaking now reads a seeker's rating straight from the
    database (see matchmaker.py's _start_seeking) rather than trusting a
    value handed in at connection time, so a test's chosen rating has to
    actually live in the db_path fixture's database, not just be passed
    around in memory. A no-op if this username is already registered
    (e.g. a reconnect scenario calling this again for the same
    username), same as a real register-then-login would behave."""
    if accounts.get_rating(db_path, username) is None:
        accounts_db.insert_user(db_path, username, "salt", "hash", rating)
    return await matchmaker.on_connect(ws, username)


async def _seek(matchmaker: Matchmaker, ws: FakeConnection) -> None:
    """Enqueue-only now (see matchmaker.py's own _start_seeking) - the
    tick right after reproduces the old inline-matching behavior every
    existing test here was written against, since with only ever a
    single Matchmaker instance under test, nothing else would ever run
    the sweep between two sequential _seek() calls."""
    await matchmaker.on_message(ws, serialize_message(SeekGameMessage()))
    await matchmaker.run_matching_tick()


async def _create_room(matchmaker: Matchmaker, ws: FakeConnection, room_id: str = "test-room") -> None:
    await matchmaker.on_message(ws, serialize_message(CreateRoomMessage(room_id=room_id)))


async def _join_room(matchmaker: Matchmaker, ws: FakeConnection, room_id: str) -> None:
    await matchmaker.on_message(ws, serialize_message(JoinRoomMessage(room_id=room_id)))


async def _cancel_room(matchmaker: Matchmaker, ws: FakeConnection) -> None:
    await matchmaker.on_message(ws, serialize_message(CancelRoomMessage()))


async def _cancel_seek(matchmaker: Matchmaker, ws: FakeConnection) -> None:
    await matchmaker.on_message(ws, serialize_message(CancelSeekMessage()))


def test_logging_in_lands_in_the_lobby_without_entering_matchmaking(db_path, accounts_base_url):
    asyncio.run(_login_lands_in_lobby(db_path, accounts_base_url))


async def _login_lands_in_lobby(db_path, accounts_base_url):
    matchmaker = _make_matchmaker(accounts_base_url)
    alice = FakeConnection("alice")

    await _connect(matchmaker, db_path, alice, "alice", 1200)

    assert alice.sent == []  # no WaitingForOpponentMessage until Play is clicked
    await matchmaker.on_disconnect(alice)


def test_clicking_play_with_no_one_else_seeking_waits_for_an_opponent(db_path, accounts_base_url):
    asyncio.run(_lone_seeker_waits(db_path, accounts_base_url))


async def _lone_seeker_waits(db_path, accounts_base_url):
    matchmaker = _make_matchmaker(accounts_base_url)
    alice = FakeConnection("alice")

    await _connect(matchmaker, db_path, alice, "alice", 1200)
    await _seek(matchmaker, alice)

    assert _last_type(alice) == protocol.WAITING_FOR_OPPONENT
    await matchmaker.on_disconnect(alice)


def test_second_seeker_within_elo_range_pairs_as_white_and_black(db_path, accounts_base_url):
    asyncio.run(_second_seeker_pairs(db_path, accounts_base_url))


async def _second_seeker_pairs(db_path, accounts_base_url):
    relay_opener = FakeRelayOpener()
    matchmaker = _make_matchmaker(accounts_base_url, relay_opener)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")

    await _connect(matchmaker, db_path, alice, "alice", 1200)
    await _connect(matchmaker, db_path, bob, "bob", 1250)
    await _seek(matchmaker, alice)
    await _seek(matchmaker, bob)

    # Stage 4a: Matchmaker never sends MatchFoundMessage itself anymore -
    # that's the Shard-hosted GameRoom's job, once the relay session it's
    # signaled here actually reaches it (see test_relay_integration.py).
    # What Matchmaker owns and can be asserted here is the *decision*:
    # who's paired with whom, as which color, into which room.
    alice_routing = relay_opener.last_for(alice)
    bob_routing = relay_opener.last_for(bob)
    assert isinstance(alice_routing, shard_protocol.HostSeatMessage)
    assert isinstance(bob_routing, shard_protocol.HostSeatMessage)
    assert alice_routing.color == WHITE
    assert bob_routing.color == BLACK
    assert alice_routing.room_id == bob_routing.room_id
    assert alice_routing.opponent_username == "bob"
    assert bob_routing.opponent_username == "alice"

    await matchmaker.on_disconnect(alice)
    await matchmaker.on_disconnect(bob)


def test_seeker_outside_elo_range_is_not_paired(db_path, accounts_base_url):
    asyncio.run(_out_of_range_seeker_not_paired(db_path, accounts_base_url))


async def _out_of_range_seeker_not_paired(db_path, accounts_base_url):
    matchmaker = _make_matchmaker(accounts_base_url)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")

    await _connect(matchmaker, db_path, alice, "alice", 1200)
    await _connect(matchmaker, db_path, bob, "bob", 1400)  # 200 points apart - outside the +-100 window
    await _seek(matchmaker, alice)
    await _seek(matchmaker, bob)

    assert _last_type(alice) == protocol.WAITING_FOR_OPPONENT
    assert _last_type(bob) == protocol.WAITING_FOR_OPPONENT

    await matchmaker.on_disconnect(alice)
    await matchmaker.on_disconnect(bob)


def test_seeking_uses_the_players_current_rating_not_their_rating_at_login(db_path, accounts_base_url):
    """A player's rating can move during their session (e.g. after
    finishing a game and clicking Play again) - matchmaking must weigh
    that current rating, not the value captured back when they first
    connected (see matchmaker.py's _start_seeking, which now fetches
    fresh from the database on every seek instead of a login-time
    cache)."""
    asyncio.run(_seeking_uses_current_rating_scenario(db_path, accounts_base_url))


async def _seeking_uses_current_rating_scenario(db_path, accounts_base_url):
    matchmaker = _make_matchmaker(accounts_base_url)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")
    await _connect(matchmaker, db_path, alice, "alice", 1200)
    await _connect(matchmaker, db_path, bob, "bob", 1250)  # in range at login time

    # alice's rating moves outside bob's range before she seeks - e.g.
    # she just finished (and lost) a game against someone else
    accounts_db.write_ratings(db_path, "alice", 1000, "bob", 1250)

    await _seek(matchmaker, alice)
    await _seek(matchmaker, bob)

    assert _last_type(alice) == protocol.WAITING_FOR_OPPONENT
    assert _last_type(bob) == protocol.WAITING_FOR_OPPONENT

    await matchmaker.on_disconnect(alice)
    await matchmaker.on_disconnect(bob)


def test_seeker_pairs_with_an_in_range_seeker_while_an_out_of_range_seeker_keeps_waiting(db_path, accounts_base_url):
    asyncio.run(_paired_with_in_range_seeker(db_path, accounts_base_url))


async def _paired_with_in_range_seeker(db_path, accounts_base_url):
    relay_opener = FakeRelayOpener()
    matchmaker = _make_matchmaker(accounts_base_url, relay_opener)
    alice = FakeConnection("alice")  # 1000 - out of range of dave (diff 300)
    carol = FakeConnection("carol")  # 1250 - in range of dave (diff 50)
    dave = FakeConnection("dave")  # 1300

    await _connect(matchmaker, db_path, alice, "alice", 1000)
    await _connect(matchmaker, db_path, carol, "carol", 1250)
    await _connect(matchmaker, db_path, dave, "dave", 1300)
    await _seek(matchmaker, alice)
    await _seek(matchmaker, carol)
    await _seek(matchmaker, dave)

    assert _last_type(alice) == protocol.WAITING_FOR_OPPONENT
    assert isinstance(relay_opener.last_for(carol), shard_protocol.HostSeatMessage)
    assert isinstance(relay_opener.last_for(dave), shard_protocol.HostSeatMessage)

    await matchmaker.on_disconnect(alice)
    await matchmaker.on_disconnect(carol)
    await matchmaker.on_disconnect(dave)


def test_matchmaker_pairs_a_third_and_fourth_seeker_independently(db_path, accounts_base_url):
    asyncio.run(_third_and_fourth_pair(db_path, accounts_base_url))


async def _third_and_fourth_pair(db_path, accounts_base_url):
    relay_opener = FakeRelayOpener()
    matchmaker = _make_matchmaker(accounts_base_url, relay_opener)
    alice, bob, carol, dave = (FakeConnection(name) for name in "abcd")

    await _connect(matchmaker, db_path, alice, "alice", 1200)
    await _connect(matchmaker, db_path, bob, "bob", 1200)
    await _seek(matchmaker, alice)
    await _seek(matchmaker, bob)  # first room: alice=white, bob=black

    await _connect(matchmaker, db_path, carol, "carol", 1200)
    await _connect(matchmaker, db_path, dave, "dave", 1200)
    await _seek(matchmaker, carol)
    assert _last_type(carol) == protocol.WAITING_FOR_OPPONENT
    await _seek(matchmaker, dave)

    carol_routing = relay_opener.last_for(carol)
    dave_routing = relay_opener.last_for(dave)
    assert carol_routing.color == WHITE
    assert dave_routing.color == BLACK
    # a genuinely separate room from alice/bob's
    assert carol_routing.room_id == dave_routing.room_id
    assert carol_routing.room_id != relay_opener.last_for(alice).room_id

    for connection in (alice, bob, carol, dave):
        await matchmaker.on_disconnect(connection)


def test_waiting_seeker_gets_no_opponent_found_after_timeout(monkeypatch, db_path, accounts_base_url):
    monkeypatch.setattr(protocol, "MATCHMAKING_TIMEOUT_SECONDS", 0.05)
    asyncio.run(_timeout_scenario(db_path, accounts_base_url))


async def _timeout_scenario(db_path, accounts_base_url):
    matchmaker = _make_matchmaker(accounts_base_url)
    alice = FakeConnection("alice")

    await _connect(matchmaker, db_path, alice, "alice", 1200)
    await _seek(matchmaker, alice)
    await asyncio.sleep(0.1)
    # No background task anymore (see matchmaker.py's run_matching_tick) -
    # timeout sweep only ever runs on the next tick, same as a real
    # Matchmaking Service's own periodic loop would provide.
    await matchmaker.run_matching_tick()

    assert _last_type(alice) == protocol.NO_OPPONENT_FOUND


def test_cancel_seek_returns_the_waiting_seeker_to_the_lobby(db_path, accounts_base_url):
    asyncio.run(_cancel_seek_scenario(db_path, accounts_base_url))


async def _cancel_seek_scenario(db_path, accounts_base_url):
    matchmaker = _make_matchmaker(accounts_base_url)
    alice = FakeConnection("alice")
    await _connect(matchmaker, db_path, alice, "alice", 1200)
    await _seek(matchmaker, alice)

    await _cancel_seek(matchmaker, alice)

    assert _last_type(alice) == protocol.SEEK_CANCELLED

    bob = FakeConnection("bob")
    await _connect(matchmaker, db_path, bob, "bob", 1200)
    await _seek(matchmaker, bob)
    assert _last_type(bob) == protocol.WAITING_FOR_OPPONENT  # not silently paired with the cancelled alice


def test_cancel_seek_with_nothing_pending_is_a_no_op(db_path, accounts_base_url):
    asyncio.run(_cancel_seek_no_op_scenario(db_path, accounts_base_url))


async def _cancel_seek_no_op_scenario(db_path, accounts_base_url):
    matchmaker = _make_matchmaker(accounts_base_url)
    alice = FakeConnection("alice")
    await _connect(matchmaker, db_path, alice, "alice", 1200)

    await _cancel_seek(matchmaker, alice)  # never clicked Play - nothing to cancel

    assert alice.sent == []


def test_disconnecting_a_waiting_seeker_frees_the_matchmaker(db_path, accounts_base_url):
    asyncio.run(_disconnect_while_waiting(db_path, accounts_base_url))


async def _disconnect_while_waiting(db_path, accounts_base_url):
    matchmaker = _make_matchmaker(accounts_base_url)
    alice = FakeConnection("alice")
    await _connect(matchmaker, db_path, alice, "alice", 1200)
    await _seek(matchmaker, alice)
    await matchmaker.on_disconnect(alice)

    bob = FakeConnection("bob")
    await _connect(matchmaker, db_path, bob, "bob", 1200)
    await _seek(matchmaker, bob)
    assert _last_type(bob) == protocol.WAITING_FOR_OPPONENT  # not silently paired with the departed alice


def test_second_login_with_the_same_username_while_the_first_is_waiting_is_rejected(db_path, accounts_base_url):
    asyncio.run(_duplicate_login_while_waiting(db_path, accounts_base_url))


async def _duplicate_login_while_waiting(db_path, accounts_base_url):
    matchmaker = _make_matchmaker(accounts_base_url)
    alice = FakeConnection("alice")
    alice_again = FakeConnection("alice-again")

    accepted_first = await _connect(matchmaker, db_path, alice, "alice", 1200)
    await _seek(matchmaker, alice)
    accepted_second = await _connect(matchmaker, db_path, alice_again, "alice", 1200)

    assert accepted_first is True
    assert accepted_second is False
    assert _last_type(alice_again) == protocol.LOGIN_FAILED
    assert _last_type(alice) == protocol.WAITING_FOR_OPPONENT  # the original session is untouched

    await matchmaker.on_disconnect(alice)


def test_second_login_with_the_same_username_while_the_first_is_in_a_match_is_rejected(db_path, accounts_base_url):
    asyncio.run(_duplicate_login_while_matched(db_path, accounts_base_url))


async def _duplicate_login_while_matched(db_path, accounts_base_url):
    relay_opener = FakeRelayOpener()
    matchmaker = _make_matchmaker(accounts_base_url, relay_opener)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")
    await _connect(matchmaker, db_path, alice, "alice", 1200)
    await _connect(matchmaker, db_path, bob, "bob", 1200)
    await _seek(matchmaker, alice)
    await _seek(matchmaker, bob)  # alice + bob now matched

    alice_again = FakeConnection("alice-again")
    accepted = await _connect(matchmaker, db_path, alice_again, "alice", 1200)

    assert accepted is False
    assert _last_type(alice_again) == protocol.LOGIN_FAILED
    assert isinstance(relay_opener.last_for(alice), shard_protocol.HostSeatMessage)  # the real session's match is unaffected

    await matchmaker.on_disconnect(alice)
    await matchmaker.on_disconnect(bob)


def test_reconnecting_signals_the_shard_with_the_remembered_room_and_color(db_path, accounts_base_url):
    """Whether the Shard actually *accepts* this reconnect (grace period
    not yet expired) is exercised end-to-end, against a real Shard, in
    test_relay_integration.py - Matchmaker's own job is just remembering
    which room/color to signal and firing that signal (see on_connect,
    on_disconnect)."""
    asyncio.run(_reconnect_signal_scenario(db_path, accounts_base_url))


async def _reconnect_signal_scenario(db_path, accounts_base_url):
    relay_opener = FakeRelayOpener()
    matchmaker = _make_matchmaker(accounts_base_url, relay_opener)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")
    await _connect(matchmaker, db_path, alice, "alice", 1200)
    await _connect(matchmaker, db_path, bob, "bob", 1200)
    await _seek(matchmaker, alice)
    await _seek(matchmaker, bob)  # alice=white, bob=black
    room_id = relay_opener.last_for(alice).room_id

    await matchmaker.on_disconnect(alice)
    disconnected_raw = await matchmaker._redis.get(f"{matchmaker._disconnected_key_prefix}alice")
    assert json.loads(disconnected_raw) == {"room_id": room_id, "color": WHITE}

    alice_new = FakeConnection("alice-reconnected")
    await _connect(matchmaker, db_path, alice_new, "alice", 1200)

    reconnect_routing = relay_opener.last_for(alice_new)
    assert isinstance(reconnect_routing, shard_protocol.ReconnectMessage)
    assert reconnect_routing.room_id == room_id
    assert reconnect_routing.color == WHITE
    # consumed by the reconnect attempt (on_connect's own getdel)
    assert await matchmaker._redis.get(f"{matchmaker._disconnected_key_prefix}alice") is None

    await matchmaker.on_disconnect(alice_new)
    await matchmaker.on_disconnect(bob)


def test_on_leave_relay_clears_room_membership_so_a_later_disconnect_is_ordinary(db_path, accounts_base_url):
    """Stage 4a: once a relay session ends without the real socket
    closing (a rejected reconnect, or "Back to Lobby" - see
    ws_gateway.py's mode-switching loop), the Gateway calls
    on_leave_relay so Matchmaker doesn't mistake a later, genuine lobby
    disconnect for a mid-game one."""
    asyncio.run(_leave_relay_scenario(db_path, accounts_base_url))


async def _leave_relay_scenario(db_path, accounts_base_url):
    relay_opener = FakeRelayOpener()
    matchmaker = _make_matchmaker(accounts_base_url, relay_opener)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")
    await _connect(matchmaker, db_path, alice, "alice", 1200)
    await _connect(matchmaker, db_path, bob, "bob", 1200)
    await _seek(matchmaker, alice)
    await _seek(matchmaker, bob)
    assert await matchmaker._redis.hget(matchmaker._room_of_key, alice.connection_id) is not None

    await matchmaker.on_leave_relay(alice)
    assert await matchmaker._redis.hget(matchmaker._room_of_key, alice.connection_id) is None

    await matchmaker.on_disconnect(alice)  # now an ordinary lobby disconnect
    assert await matchmaker._redis.get(f"{matchmaker._disconnected_key_prefix}alice") is None

    await matchmaker.on_disconnect(bob)


# ==========================================
# Rooms: Create/Join/Cancel, spectators
# ==========================================

def test_create_room_sends_room_created_with_an_id(db_path, accounts_base_url):
    asyncio.run(_create_room_scenario(db_path, accounts_base_url))


async def _create_room_scenario(db_path, accounts_base_url):
    matchmaker = _make_matchmaker(accounts_base_url)
    alice = FakeConnection("alice")
    await _connect(matchmaker, db_path, alice, "alice", 1200)

    await _create_room(matchmaker, alice)

    assert _last_type(alice) == protocol.ROOM_CREATED
    assert alice.sent[-1]["room_id"]

    await matchmaker.on_disconnect(alice)


def test_joining_a_pending_room_starts_a_game_with_creator_as_white(db_path, accounts_base_url):
    asyncio.run(_join_as_opponent_scenario(db_path, accounts_base_url))


async def _join_as_opponent_scenario(db_path, accounts_base_url):
    relay_opener = FakeRelayOpener()
    matchmaker = _make_matchmaker(accounts_base_url, relay_opener)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")
    await _connect(matchmaker, db_path, alice, "alice", 1200)
    await _connect(matchmaker, db_path, bob, "bob", 1200)
    await _create_room(matchmaker, alice)
    room_id = alice.sent[-1]["room_id"]

    await _join_room(matchmaker, bob, room_id)

    alice_routing = relay_opener.last_for(alice)
    bob_routing = relay_opener.last_for(bob)
    assert isinstance(alice_routing, shard_protocol.HostSeatMessage)
    assert alice_routing.color == WHITE
    assert alice_routing.room_id == room_id
    assert isinstance(bob_routing, shard_protocol.HostSeatMessage)
    assert bob_routing.color == BLACK
    assert bob_routing.room_id == room_id

    await matchmaker.on_disconnect(alice)
    await matchmaker.on_disconnect(bob)


def test_joining_a_started_room_sends_spectating_instead_of_match_found(db_path, accounts_base_url):
    asyncio.run(_join_as_spectator_scenario(db_path, accounts_base_url))


async def _join_as_spectator_scenario(db_path, accounts_base_url):
    matchmaker = _make_matchmaker(accounts_base_url)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")
    carol = FakeConnection("carol")
    await _connect(matchmaker, db_path, alice, "alice", 1200)
    await _connect(matchmaker, db_path, bob, "bob", 1200)
    await _connect(matchmaker, db_path, carol, "carol", 1200)
    await _create_room(matchmaker, alice)
    room_id = alice.sent[-1]["room_id"]
    await _join_room(matchmaker, bob, room_id)

    await _join_room(matchmaker, carol, room_id)

    assert _last_type(carol) == protocol.SPECTATING
    assert carol.sent[-1]["room_id"] == room_id
    assert carol.sent[-1]["white_username"] == "alice"
    assert carol.sent[-1]["black_username"] == "bob"

    await matchmaker.on_disconnect(alice)
    await matchmaker.on_disconnect(bob)
    await matchmaker.on_disconnect(carol)


def test_joining_an_unknown_room_id_sends_join_room_failed(db_path, accounts_base_url):
    asyncio.run(_join_unknown_room_scenario(db_path, accounts_base_url))


async def _join_unknown_room_scenario(db_path, accounts_base_url):
    matchmaker = _make_matchmaker(accounts_base_url)
    bob = FakeConnection("bob")
    await _connect(matchmaker, db_path, bob, "bob", 1200)

    await _join_room(matchmaker, bob, "NOSUCH")

    assert _last_type(bob) == protocol.JOIN_ROOM_FAILED
    assert bob.sent[-1]["reason"] == "room_not_found"

    await matchmaker.on_disconnect(bob)


def test_cancel_room_returns_the_creator_to_the_lobby(db_path, accounts_base_url):
    asyncio.run(_cancel_room_scenario(db_path, accounts_base_url))


async def _cancel_room_scenario(db_path, accounts_base_url):
    matchmaker = _make_matchmaker(accounts_base_url)
    alice = FakeConnection("alice")
    await _connect(matchmaker, db_path, alice, "alice", 1200)
    await _create_room(matchmaker, alice)
    room_id = alice.sent[-1]["room_id"]

    await _cancel_room(matchmaker, alice)

    assert _last_type(alice) == protocol.ROOM_CANCELLED
    bob = FakeConnection("bob")
    await _connect(matchmaker, db_path, bob, "bob", 1200)
    await _join_room(matchmaker, bob, room_id)
    assert _last_type(bob) == protocol.JOIN_ROOM_FAILED  # the cancelled room is really gone

    await matchmaker.on_disconnect(alice)
    await matchmaker.on_disconnect(bob)


def test_spectator_disconnect_does_not_pause_the_room(db_path, accounts_base_url):
    asyncio.run(_spectator_disconnect_scenario(db_path, accounts_base_url))


async def _spectator_disconnect_scenario(db_path, accounts_base_url):
    relay_opener = FakeRelayOpener()
    matchmaker = _make_matchmaker(accounts_base_url, relay_opener)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")
    carol = FakeConnection("carol")
    await _connect(matchmaker, db_path, alice, "alice", 1200)
    await _connect(matchmaker, db_path, bob, "bob", 1200)
    await _connect(matchmaker, db_path, carol, "carol", 1200)
    await _create_room(matchmaker, alice)
    room_id = alice.sent[-1]["room_id"]
    await _join_room(matchmaker, bob, room_id)
    await _join_room(matchmaker, carol, room_id)
    calls_before = len(relay_opener.calls)

    await matchmaker.on_disconnect(carol)

    # Neither real player was ever told the opponent disconnected, and no
    # further relay request was fired - a spectator leaving is a plain
    # no-op, not a game-pausing event.
    assert len(relay_opener.calls) == calls_before
    assert all(entry["type"] != protocol.OPPONENT_DISCONNECTED for entry in alice.sent)
    assert all(entry["type"] != protocol.OPPONENT_DISCONNECTED for entry in bob.sent)

    await matchmaker.on_disconnect(alice)
    await matchmaker.on_disconnect(bob)


def test_room_creator_disconnecting_before_anyone_joins_frees_the_room_id(db_path, accounts_base_url):
    asyncio.run(_pending_creator_disconnect_scenario(db_path, accounts_base_url))


async def _pending_creator_disconnect_scenario(db_path, accounts_base_url):
    matchmaker = _make_matchmaker(accounts_base_url)
    alice = FakeConnection("alice")
    await _connect(matchmaker, db_path, alice, "alice", 1200)
    await _create_room(matchmaker, alice)
    room_id = alice.sent[-1]["room_id"]

    await matchmaker.on_disconnect(alice)

    bob = FakeConnection("bob")
    await _connect(matchmaker, db_path, bob, "bob", 1200)
    await _join_room(matchmaker, bob, room_id)
    assert _last_type(bob) == protocol.JOIN_ROOM_FAILED  # the id was freed, not left dangling

    await matchmaker.on_disconnect(bob)


def test_create_room_uses_the_players_typed_name(db_path, accounts_base_url):
    asyncio.run(_create_room_typed_name_scenario(db_path, accounts_base_url))


async def _create_room_typed_name_scenario(db_path, accounts_base_url):
    matchmaker = _make_matchmaker(accounts_base_url)
    alice = FakeConnection("alice")
    await _connect(matchmaker, db_path, alice, "alice", 1200)

    await _create_room(matchmaker, alice, room_id="efrat-room")

    assert alice.sent[-1]["room_id"] == "efrat-room"

    await matchmaker.on_disconnect(alice)


def test_create_room_with_an_already_taken_name_sends_create_room_failed(db_path, accounts_base_url):
    asyncio.run(_create_room_name_taken_scenario(db_path, accounts_base_url))


async def _create_room_name_taken_scenario(db_path, accounts_base_url):
    matchmaker = _make_matchmaker(accounts_base_url)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")
    await _connect(matchmaker, db_path, alice, "alice", 1200)
    await _connect(matchmaker, db_path, bob, "bob", 1200)
    await _create_room(matchmaker, alice, room_id="efrat-room")

    await _create_room(matchmaker, bob, room_id="efrat-room")

    assert _last_type(bob) == protocol.CREATE_ROOM_FAILED
    assert bob.sent[-1]["reason"] == "room_name_taken"

    await matchmaker.on_disconnect(alice)
    await matchmaker.on_disconnect(bob)


def test_create_room_while_already_in_a_room_sends_create_room_failed(db_path, accounts_base_url):
    asyncio.run(_create_room_while_already_in_one_scenario(db_path, accounts_base_url))


async def _create_room_while_already_in_one_scenario(db_path, accounts_base_url):
    matchmaker = _make_matchmaker(accounts_base_url)
    alice = FakeConnection("alice")
    await _connect(matchmaker, db_path, alice, "alice", 1200)
    await _create_room(matchmaker, alice, room_id="room-one")

    await _create_room(matchmaker, alice, room_id="room-two")

    assert _last_type(alice) == protocol.CREATE_ROOM_FAILED
    assert alice.sent[-1]["reason"] == "already_in_a_room"

    await matchmaker.on_disconnect(alice)

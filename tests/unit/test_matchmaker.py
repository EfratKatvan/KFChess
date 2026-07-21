import asyncio
import json

import pytest

from kungfu_chess.model.piece import WHITE, BLACK
from kungfu_chess.server import accounts, protocol
from kungfu_chess.server.matchmaker import Matchmaker
from kungfu_chess.server.messages import CancelRoomMessage, CreateRoomMessage, JoinRoomMessage, SeekGameMessage
from kungfu_chess.server.serialization import serialize_message


class FakeConnection:
    """A stand-in for websockets.asyncio.server.ServerConnection - only
    needs an async send() that records what was sent, since Matchmaker/
    GameRoom never call anything else on a connection directly."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.sent = []

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


def _last_type(connection: FakeConnection):
    return connection.sent[-1]["type"] if connection.sent else None


async def _seek(matchmaker: Matchmaker, ws: FakeConnection) -> None:
    await matchmaker.on_message(ws, serialize_message(SeekGameMessage()))


async def _create_room(matchmaker: Matchmaker, ws: FakeConnection, room_id: str = "test-room") -> None:
    await matchmaker.on_message(ws, serialize_message(CreateRoomMessage(room_id=room_id)))


async def _join_room(matchmaker: Matchmaker, ws: FakeConnection, room_id: str) -> None:
    await matchmaker.on_message(ws, serialize_message(JoinRoomMessage(room_id=room_id)))


async def _cancel_room(matchmaker: Matchmaker, ws: FakeConnection) -> None:
    await matchmaker.on_message(ws, serialize_message(CancelRoomMessage()))


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test_users.db")
    accounts.init_db(path)
    return path


def test_logging_in_lands_in_the_lobby_without_entering_matchmaking(db_path):
    asyncio.run(_login_lands_in_lobby(db_path))


async def _login_lands_in_lobby(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")

    await matchmaker.on_connect(alice, "alice", 1200)

    assert alice.sent == []  # no WaitingForOpponentMessage until Play is clicked
    await matchmaker.on_disconnect(alice)


def test_clicking_play_with_no_one_else_seeking_waits_for_an_opponent(db_path):
    asyncio.run(_lone_seeker_waits(db_path))


async def _lone_seeker_waits(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")

    await matchmaker.on_connect(alice, "alice", 1200)
    await _seek(matchmaker, alice)

    assert _last_type(alice) == protocol.WAITING_FOR_OPPONENT
    await matchmaker.on_disconnect(alice)


def test_second_seeker_within_elo_range_pairs_as_white_and_black(db_path):
    asyncio.run(_second_seeker_pairs(db_path))


async def _second_seeker_pairs(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")

    await matchmaker.on_connect(alice, "alice", 1200)
    await matchmaker.on_connect(bob, "bob", 1250)
    await _seek(matchmaker, alice)
    await _seek(matchmaker, bob)

    assert _last_type(alice) == protocol.MATCH_FOUND
    assert _last_type(bob) == protocol.MATCH_FOUND
    assert alice.sent[-1]["color"] == WHITE
    assert bob.sent[-1]["color"] == BLACK

    await matchmaker.on_disconnect(alice)
    await matchmaker.on_disconnect(bob)


def test_seeker_outside_elo_range_is_not_paired(db_path):
    asyncio.run(_out_of_range_seeker_not_paired(db_path))


async def _out_of_range_seeker_not_paired(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")

    await matchmaker.on_connect(alice, "alice", 1200)
    await matchmaker.on_connect(bob, "bob", 1400)  # 200 points apart - outside the +-100 window
    await _seek(matchmaker, alice)
    await _seek(matchmaker, bob)

    assert _last_type(alice) == protocol.WAITING_FOR_OPPONENT
    assert _last_type(bob) == protocol.WAITING_FOR_OPPONENT

    await matchmaker.on_disconnect(alice)
    await matchmaker.on_disconnect(bob)


def test_seeker_pairs_with_an_in_range_seeker_while_an_out_of_range_seeker_keeps_waiting(db_path):
    asyncio.run(_paired_with_in_range_seeker(db_path))


async def _paired_with_in_range_seeker(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")  # 1000 - out of range of dave (diff 300)
    carol = FakeConnection("carol")  # 1250 - in range of dave (diff 50)
    dave = FakeConnection("dave")  # 1300

    await matchmaker.on_connect(alice, "alice", 1000)
    await matchmaker.on_connect(carol, "carol", 1250)
    await matchmaker.on_connect(dave, "dave", 1300)
    await _seek(matchmaker, alice)
    await _seek(matchmaker, carol)
    await _seek(matchmaker, dave)

    assert _last_type(alice) == protocol.WAITING_FOR_OPPONENT
    assert _last_type(carol) == protocol.MATCH_FOUND
    assert _last_type(dave) == protocol.MATCH_FOUND

    await matchmaker.on_disconnect(alice)
    await matchmaker.on_disconnect(carol)
    await matchmaker.on_disconnect(dave)


def test_matchmaker_pairs_a_third_and_fourth_seeker_independently(db_path):
    asyncio.run(_third_and_fourth_pair(db_path))


async def _third_and_fourth_pair(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice, bob, carol, dave = (FakeConnection(name) for name in "abcd")

    await matchmaker.on_connect(alice, "alice", 1200)
    await matchmaker.on_connect(bob, "bob", 1200)
    await _seek(matchmaker, alice)
    await _seek(matchmaker, bob)  # first room: alice=white, bob=black

    await matchmaker.on_connect(carol, "carol", 1200)
    await matchmaker.on_connect(dave, "dave", 1200)
    await _seek(matchmaker, carol)
    assert _last_type(carol) == protocol.WAITING_FOR_OPPONENT
    await _seek(matchmaker, dave)

    assert carol.sent[-1]["color"] == WHITE
    assert dave.sent[-1]["color"] == BLACK

    for connection in (alice, bob, carol, dave):
        await matchmaker.on_disconnect(connection)


def test_waiting_seeker_gets_no_opponent_found_after_timeout(monkeypatch, db_path):
    monkeypatch.setattr(protocol, "MATCHMAKING_TIMEOUT_SECONDS", 0.05)
    asyncio.run(_timeout_scenario(db_path))


async def _timeout_scenario(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")

    await matchmaker.on_connect(alice, "alice", 1200)
    await _seek(matchmaker, alice)
    await asyncio.sleep(0.1)

    assert _last_type(alice) == protocol.NO_OPPONENT_FOUND


def test_disconnecting_a_waiting_seeker_frees_the_matchmaker(db_path):
    asyncio.run(_disconnect_while_waiting(db_path))


async def _disconnect_while_waiting(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    await matchmaker.on_connect(alice, "alice", 1200)
    await _seek(matchmaker, alice)
    await matchmaker.on_disconnect(alice)

    bob = FakeConnection("bob")
    await matchmaker.on_connect(bob, "bob", 1200)
    await _seek(matchmaker, bob)
    assert _last_type(bob) == protocol.WAITING_FOR_OPPONENT  # not silently paired with the departed alice


def test_reconnecting_with_the_same_username_rejoins_the_same_room_instead_of_the_lobby(db_path):
    asyncio.run(_reconnect_rejoins_room(db_path))


async def _reconnect_rejoins_room(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")
    await matchmaker.on_connect(alice, "alice", 1200)
    await matchmaker.on_connect(bob, "bob", 1200)
    await _seek(matchmaker, alice)
    await _seek(matchmaker, bob)  # alice=white, bob=black

    await matchmaker.on_disconnect(alice)
    assert _last_type(bob) == protocol.OPPONENT_DISCONNECTED

    alice_new = FakeConnection("alice-reconnected")
    await matchmaker.on_connect(alice_new, "alice", 1200)

    # reattached to the same room, not requeued - gets match_found again (so it re-learns its own color),
    # never waiting_for_opponent (that would mean it landed back in the lobby instead)
    assert _last_type(alice_new) == protocol.MATCH_FOUND
    assert alice_new.sent[-1]["color"] == WHITE
    assert _last_type(bob) == protocol.OPPONENT_RECONNECTED

    await matchmaker.on_disconnect(alice_new)
    await matchmaker.on_disconnect(bob)


def test_second_login_with_the_same_username_while_the_first_is_waiting_is_rejected(db_path):
    asyncio.run(_duplicate_login_while_waiting(db_path))


async def _duplicate_login_while_waiting(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    alice_again = FakeConnection("alice-again")

    accepted_first = await matchmaker.on_connect(alice, "alice", 1200)
    await _seek(matchmaker, alice)
    accepted_second = await matchmaker.on_connect(alice_again, "alice", 1200)

    assert accepted_first is True
    assert accepted_second is False
    assert _last_type(alice_again) == protocol.LOGIN_FAILED
    assert _last_type(alice) == protocol.WAITING_FOR_OPPONENT  # the original session is untouched

    await matchmaker.on_disconnect(alice)


def test_second_login_with_the_same_username_while_the_first_is_in_a_match_is_rejected(db_path):
    asyncio.run(_duplicate_login_while_matched(db_path))


async def _duplicate_login_while_matched(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")
    await matchmaker.on_connect(alice, "alice", 1200)
    await matchmaker.on_connect(bob, "bob", 1200)
    await _seek(matchmaker, alice)
    await _seek(matchmaker, bob)  # alice + bob now matched

    alice_again = FakeConnection("alice-again")
    accepted = await matchmaker.on_connect(alice_again, "alice", 1200)

    assert accepted is False
    assert _last_type(alice_again) == protocol.LOGIN_FAILED
    assert _last_type(alice) == protocol.MATCH_FOUND  # the real session's match is unaffected

    await matchmaker.on_disconnect(alice)
    await matchmaker.on_disconnect(bob)


def test_reconnecting_with_the_same_username_is_allowed_after_the_original_disconnects(db_path):
    """The duplicate-login rejection must not block a genuine
    reconnect - only a *simultaneous* second session is rejected."""
    asyncio.run(_reconnect_not_blocked_by_duplicate_check(db_path))


async def _reconnect_not_blocked_by_duplicate_check(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")
    await matchmaker.on_connect(alice, "alice", 1200)
    await matchmaker.on_connect(bob, "bob", 1200)
    await _seek(matchmaker, alice)
    await _seek(matchmaker, bob)

    await matchmaker.on_disconnect(alice)  # alice's connection is now gone

    alice_new = FakeConnection("alice-reconnected")
    accepted = await matchmaker.on_connect(alice_new, "alice", 1200)

    assert accepted is True
    assert _last_type(alice_new) == protocol.MATCH_FOUND

    await matchmaker.on_disconnect(alice_new)
    await matchmaker.on_disconnect(bob)


def test_reconnecting_after_the_grace_period_falls_back_to_the_lobby(db_path, monkeypatch):
    monkeypatch.setattr(protocol, "DISCONNECT_GRACE_SECONDS", 0.05)
    asyncio.run(_reconnect_after_grace_expired(db_path))


async def _reconnect_after_grace_expired(db_path):
    accounts.authenticate(db_path, "alice", "pw")
    accounts.authenticate(db_path, "bob", "pw")

    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")
    await matchmaker.on_connect(alice, "alice", 1200)
    await matchmaker.on_connect(bob, "bob", 1200)
    await _seek(matchmaker, alice)
    await _seek(matchmaker, bob)

    await matchmaker.on_disconnect(alice)
    await asyncio.sleep(0.15)  # past the (shortened) grace period - room has already auto-resigned

    alice_new = FakeConnection("alice-too-late")
    await matchmaker.on_connect(alice_new, "alice", 1200)
    assert alice_new.sent == []  # lands in the lobby, same as a fresh login - no auto-matchmaking

    await _seek(matchmaker, alice_new)
    assert _last_type(alice_new) == protocol.WAITING_FOR_OPPONENT  # treated as a fresh matchmaking candidate

    await matchmaker.on_disconnect(alice_new)
    await matchmaker.on_disconnect(bob)


# ==========================================
# Rooms: Create/Join/Cancel, spectators
# ==========================================

def test_create_room_sends_room_created_with_an_id(db_path):
    asyncio.run(_create_room_scenario(db_path))


async def _create_room_scenario(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    await matchmaker.on_connect(alice, "alice", 1200)

    await _create_room(matchmaker, alice)

    assert _last_type(alice) == protocol.ROOM_CREATED
    assert alice.sent[-1]["room_id"]

    await matchmaker.on_disconnect(alice)


def test_joining_a_pending_room_starts_a_game_with_creator_as_white(db_path):
    asyncio.run(_join_as_opponent_scenario(db_path))


async def _join_as_opponent_scenario(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")
    await matchmaker.on_connect(alice, "alice", 1200)
    await matchmaker.on_connect(bob, "bob", 1200)
    await _create_room(matchmaker, alice)
    room_id = alice.sent[-1]["room_id"]

    await _join_room(matchmaker, bob, room_id)

    assert _last_type(alice) == protocol.MATCH_FOUND
    assert alice.sent[-1]["color"] == WHITE
    assert alice.sent[-1]["room_id"] == room_id
    assert _last_type(bob) == protocol.MATCH_FOUND
    assert bob.sent[-1]["color"] == BLACK
    assert bob.sent[-1]["room_id"] == room_id

    await matchmaker.on_disconnect(alice)
    await matchmaker.on_disconnect(bob)


def test_joining_a_started_room_sends_spectating_instead_of_match_found(db_path):
    asyncio.run(_join_as_spectator_scenario(db_path))


async def _join_as_spectator_scenario(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")
    carol = FakeConnection("carol")
    await matchmaker.on_connect(alice, "alice", 1200)
    await matchmaker.on_connect(bob, "bob", 1200)
    await matchmaker.on_connect(carol, "carol", 1200)
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


def test_joining_an_unknown_room_id_sends_join_room_failed(db_path):
    asyncio.run(_join_unknown_room_scenario(db_path))


async def _join_unknown_room_scenario(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    bob = FakeConnection("bob")
    await matchmaker.on_connect(bob, "bob", 1200)

    await _join_room(matchmaker, bob, "NOSUCH")

    assert _last_type(bob) == protocol.JOIN_ROOM_FAILED
    assert bob.sent[-1]["reason"] == "room_not_found"

    await matchmaker.on_disconnect(bob)


def test_cancel_room_returns_the_creator_to_the_lobby(db_path):
    asyncio.run(_cancel_room_scenario(db_path))


async def _cancel_room_scenario(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    await matchmaker.on_connect(alice, "alice", 1200)
    await _create_room(matchmaker, alice)
    room_id = alice.sent[-1]["room_id"]

    await _cancel_room(matchmaker, alice)

    assert _last_type(alice) == protocol.ROOM_CANCELLED
    bob = FakeConnection("bob")
    await matchmaker.on_connect(bob, "bob", 1200)
    await _join_room(matchmaker, bob, room_id)
    assert _last_type(bob) == protocol.JOIN_ROOM_FAILED  # the cancelled room is really gone

    await matchmaker.on_disconnect(alice)
    await matchmaker.on_disconnect(bob)


def test_spectator_disconnect_does_not_pause_the_room(db_path):
    asyncio.run(_spectator_disconnect_scenario(db_path))


async def _spectator_disconnect_scenario(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")
    carol = FakeConnection("carol")
    await matchmaker.on_connect(alice, "alice", 1200)
    await matchmaker.on_connect(bob, "bob", 1200)
    await matchmaker.on_connect(carol, "carol", 1200)
    await _create_room(matchmaker, alice)
    room_id = alice.sent[-1]["room_id"]
    await _join_room(matchmaker, bob, room_id)
    await _join_room(matchmaker, carol, room_id)

    await matchmaker.on_disconnect(carol)

    # Neither real player was ever told the opponent disconnected -
    # a spectator leaving is a plain no-op, not a game-pausing event.
    assert all(entry["type"] != protocol.OPPONENT_DISCONNECTED for entry in alice.sent)
    assert all(entry["type"] != protocol.OPPONENT_DISCONNECTED for entry in bob.sent)

    await matchmaker.on_disconnect(alice)
    await matchmaker.on_disconnect(bob)


def test_room_creator_disconnecting_before_anyone_joins_frees_the_room_id(db_path):
    asyncio.run(_pending_creator_disconnect_scenario(db_path))


async def _pending_creator_disconnect_scenario(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    await matchmaker.on_connect(alice, "alice", 1200)
    await _create_room(matchmaker, alice)
    room_id = alice.sent[-1]["room_id"]

    await matchmaker.on_disconnect(alice)

    bob = FakeConnection("bob")
    await matchmaker.on_connect(bob, "bob", 1200)
    await _join_room(matchmaker, bob, room_id)
    assert _last_type(bob) == protocol.JOIN_ROOM_FAILED  # the id was freed, not left dangling

    await matchmaker.on_disconnect(bob)


def test_create_room_uses_the_players_typed_name(db_path):
    asyncio.run(_create_room_typed_name_scenario(db_path))


async def _create_room_typed_name_scenario(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    await matchmaker.on_connect(alice, "alice", 1200)

    await _create_room(matchmaker, alice, room_id="efrat-room")

    assert alice.sent[-1]["room_id"] == "efrat-room"

    await matchmaker.on_disconnect(alice)


def test_create_room_with_an_already_taken_name_sends_create_room_failed(db_path):
    asyncio.run(_create_room_name_taken_scenario(db_path))


async def _create_room_name_taken_scenario(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")
    await matchmaker.on_connect(alice, "alice", 1200)
    await matchmaker.on_connect(bob, "bob", 1200)
    await _create_room(matchmaker, alice, room_id="efrat-room")

    await _create_room(matchmaker, bob, room_id="efrat-room")

    assert _last_type(bob) == protocol.CREATE_ROOM_FAILED
    assert bob.sent[-1]["reason"] == "room_name_taken"

    await matchmaker.on_disconnect(alice)
    await matchmaker.on_disconnect(bob)


def test_create_room_while_already_in_a_room_sends_create_room_failed(db_path):
    asyncio.run(_create_room_while_already_in_one_scenario(db_path))


async def _create_room_while_already_in_one_scenario(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    await matchmaker.on_connect(alice, "alice", 1200)
    await _create_room(matchmaker, alice, room_id="room-one")

    await _create_room(matchmaker, alice, room_id="room-two")

    assert _last_type(alice) == protocol.CREATE_ROOM_FAILED
    assert alice.sent[-1]["reason"] == "already_in_a_room"

    await matchmaker.on_disconnect(alice)

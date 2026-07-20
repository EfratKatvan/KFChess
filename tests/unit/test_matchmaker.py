import asyncio
import json

import pytest

from kungfu_chess.model.piece import WHITE, BLACK
from kungfu_chess.server import accounts, protocol
from kungfu_chess.server.matchmaker import Matchmaker


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


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test_users.db")
    accounts.init_db(path)
    return path


def test_lone_connection_waits_for_an_opponent(db_path):
    asyncio.run(_lone_connection_waits(db_path))


async def _lone_connection_waits(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")

    await matchmaker.on_connect(alice, "alice")

    assert _last_type(alice) == protocol.WAITING_FOR_OPPONENT
    await matchmaker.on_disconnect(alice)


def test_second_connection_pairs_with_the_first_as_white_and_black(db_path):
    asyncio.run(_second_connection_pairs(db_path))


async def _second_connection_pairs(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")

    await matchmaker.on_connect(alice, "alice")
    await matchmaker.on_connect(bob, "bob")

    assert _last_type(alice) == protocol.MATCH_FOUND
    assert _last_type(bob) == protocol.MATCH_FOUND
    assert alice.sent[-1]["color"] == WHITE
    assert bob.sent[-1]["color"] == BLACK

    await matchmaker.on_disconnect(alice)
    await matchmaker.on_disconnect(bob)


def test_matchmaker_pairs_a_third_and_fourth_connection_independently(db_path):
    asyncio.run(_third_and_fourth_pair(db_path))


async def _third_and_fourth_pair(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice, bob, carol, dave = (FakeConnection(name) for name in "abcd")

    await matchmaker.on_connect(alice, "alice")
    await matchmaker.on_connect(bob, "bob")  # first room: alice=white, bob=black

    await matchmaker.on_connect(carol, "carol")
    assert _last_type(carol) == protocol.WAITING_FOR_OPPONENT
    await matchmaker.on_connect(dave, "dave")

    assert carol.sent[-1]["color"] == WHITE
    assert dave.sent[-1]["color"] == BLACK

    for connection in (alice, bob, carol, dave):
        await matchmaker.on_disconnect(connection)


def test_waiting_connection_gets_no_opponent_found_after_timeout(monkeypatch, db_path):
    monkeypatch.setattr(protocol, "MATCHMAKING_TIMEOUT_SECONDS", 0.05)
    asyncio.run(_timeout_scenario(db_path))


async def _timeout_scenario(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")

    await matchmaker.on_connect(alice, "alice")
    await asyncio.sleep(0.1)

    assert _last_type(alice) == protocol.NO_OPPONENT_FOUND


def test_disconnecting_a_waiting_connection_frees_the_matchmaker(db_path):
    asyncio.run(_disconnect_while_waiting(db_path))


async def _disconnect_while_waiting(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    await matchmaker.on_connect(alice, "alice")
    await matchmaker.on_disconnect(alice)

    bob = FakeConnection("bob")
    await matchmaker.on_connect(bob, "bob")
    assert _last_type(bob) == protocol.WAITING_FOR_OPPONENT  # not silently paired with the departed alice


def test_reconnecting_with_the_same_username_rejoins_the_same_room_instead_of_requeuing(db_path):
    asyncio.run(_reconnect_rejoins_room(db_path))


async def _reconnect_rejoins_room(db_path):
    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")
    await matchmaker.on_connect(alice, "alice")
    await matchmaker.on_connect(bob, "bob")  # alice=white, bob=black

    await matchmaker.on_disconnect(alice)
    assert _last_type(bob) == protocol.OPPONENT_DISCONNECTED

    alice_new = FakeConnection("alice-reconnected")
    await matchmaker.on_connect(alice_new, "alice")

    # reattached to the same room, not requeued - gets match_found again (so it re-learns its own color),
    # never waiting_for_opponent (that would mean it went through normal matchmaking instead)
    assert _last_type(alice_new) == protocol.MATCH_FOUND
    assert alice_new.sent[-1]["color"] == WHITE
    assert _last_type(bob) == protocol.OPPONENT_RECONNECTED

    await matchmaker.on_disconnect(alice_new)
    await matchmaker.on_disconnect(bob)


def test_reconnecting_after_the_grace_period_falls_back_to_normal_matchmaking(db_path, monkeypatch):
    monkeypatch.setattr(protocol, "DISCONNECT_GRACE_SECONDS", 0.05)
    asyncio.run(_reconnect_after_grace_expired(db_path))


async def _reconnect_after_grace_expired(db_path):
    accounts.authenticate(db_path, "alice", "pw")
    accounts.authenticate(db_path, "bob", "pw")

    matchmaker = Matchmaker(db_path=db_path)
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")
    await matchmaker.on_connect(alice, "alice")
    await matchmaker.on_connect(bob, "bob")

    await matchmaker.on_disconnect(alice)
    await asyncio.sleep(0.15)  # past the (shortened) grace period - room has already auto-resigned

    alice_new = FakeConnection("alice-too-late")
    await matchmaker.on_connect(alice_new, "alice")

    assert _last_type(alice_new) == protocol.WAITING_FOR_OPPONENT  # treated as a fresh matchmaking candidate

    await matchmaker.on_disconnect(alice_new)
    await matchmaker.on_disconnect(bob)

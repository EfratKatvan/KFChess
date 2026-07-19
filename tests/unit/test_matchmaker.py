import asyncio
import json

from kungfu_chess.model.piece import WHITE, BLACK
from kungfu_chess.server import protocol
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


def test_lone_connection_waits_for_an_opponent():
    asyncio.run(_lone_connection_waits())


async def _lone_connection_waits():
    matchmaker = Matchmaker()
    alice = FakeConnection("alice")

    await matchmaker.on_connect(alice)

    assert _last_type(alice) == protocol.WAITING_FOR_OPPONENT
    await matchmaker.on_disconnect(alice)


def test_second_connection_pairs_with_the_first_as_white_and_black():
    asyncio.run(_second_connection_pairs())


async def _second_connection_pairs():
    matchmaker = Matchmaker()
    alice = FakeConnection("alice")
    bob = FakeConnection("bob")

    await matchmaker.on_connect(alice)
    await matchmaker.on_connect(bob)

    assert _last_type(alice) == protocol.MATCH_FOUND
    assert _last_type(bob) == protocol.MATCH_FOUND
    assert alice.sent[-1]["color"] == WHITE
    assert bob.sent[-1]["color"] == BLACK

    await matchmaker.on_disconnect(alice)
    await matchmaker.on_disconnect(bob)


def test_matchmaker_pairs_a_third_and_fourth_connection_independently():
    asyncio.run(_third_and_fourth_pair())


async def _third_and_fourth_pair():
    matchmaker = Matchmaker()
    alice, bob, carol, dave = (FakeConnection(name) for name in "abcd")

    await matchmaker.on_connect(alice)
    await matchmaker.on_connect(bob)  # first room: alice=white, bob=black

    await matchmaker.on_connect(carol)
    assert _last_type(carol) == protocol.WAITING_FOR_OPPONENT
    await matchmaker.on_connect(dave)

    assert carol.sent[-1]["color"] == WHITE
    assert dave.sent[-1]["color"] == BLACK

    for connection in (alice, bob, carol, dave):
        await matchmaker.on_disconnect(connection)


def test_waiting_connection_gets_no_opponent_found_after_timeout(monkeypatch):
    monkeypatch.setattr(protocol, "MATCHMAKING_TIMEOUT_SECONDS", 0.05)
    asyncio.run(_timeout_scenario())


async def _timeout_scenario():
    matchmaker = Matchmaker()
    alice = FakeConnection("alice")

    await matchmaker.on_connect(alice)
    await asyncio.sleep(0.1)

    assert _last_type(alice) == protocol.NO_OPPONENT_FOUND


def test_disconnecting_a_waiting_connection_frees_the_matchmaker():
    asyncio.run(_disconnect_while_waiting())


async def _disconnect_while_waiting():
    matchmaker = Matchmaker()
    alice = FakeConnection("alice")
    await matchmaker.on_connect(alice)
    await matchmaker.on_disconnect(alice)

    bob = FakeConnection("bob")
    await matchmaker.on_connect(bob)
    assert _last_type(bob) == protocol.WAITING_FOR_OPPONENT  # not silently paired with the departed alice

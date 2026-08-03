import asyncio
import json
import uuid

import pytest

from kungfu_chess.model.piece import BLACK, WHITE
from kungfu_chess.server import accounts, accounts_db, game_shard, protocol, shard_protocol
from kungfu_chess.server.accounts_client import AccountsClient
from kungfu_chess.server.game_shard import GameShard
from kungfu_chess.server.messages import LeaveRoomMessage, SelectOrMoveMessage
from kungfu_chess.server.redis_client import get_client as get_redis_client
from kungfu_chess.server.serialization import serialize_message

_CLOSED = object()  # sentinel pushed into a FakeRelayConnection's queue on close()


class FakeRelayConnection:
    """A stand-in for a Gateway<->Shard relay connection (Stage 4a) -
    unlike test_matchmaker.py's FakeConnection, GameShard actually reads
    from its connections (the one-time routing handshake via recv(), then
    ordinary gameplay traffic via async iteration), so this needs both."""

    def __init__(self, incoming=()) -> None:
        self.sent = []
        self.closed = False
        self._incoming: "asyncio.Queue" = asyncio.Queue()
        for message in incoming:
            self._incoming.put_nowait(message)

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def recv(self) -> str:
        item = await self._incoming.get()
        if item is _CLOSED:
            raise ConnectionError("closed")
        return item

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        item = await self._incoming.get()
        if item is _CLOSED:
            raise StopAsyncIteration
        return item

    async def close(self) -> None:
        self.closed = True
        self._incoming.put_nowait(_CLOSED)

    def push(self, raw: str) -> None:
        self._incoming.put_nowait(raw)


def _sent_types(connection: FakeRelayConnection):
    return [m["type"] for m in connection.sent]


async def _wait_until(predicate, timeout: float = 2.0) -> None:
    """Polls until predicate() is true - a fixed short sleep is flaky
    here since GameShard's own work (GameAllocator.allocate, GameRoom.
    start) makes real cross-thread HTTP calls to accounts_base_url's
    background-loop server (see conftest.py) and real Redis round-trips,
    neither of which has a fixed, guaranteed-fast completion time."""
    deadline = asyncio.get_event_loop().time() + timeout
    while not predicate():
        if asyncio.get_event_loop().time() >= deadline:
            raise AssertionError("condition not met before timeout")
        await asyncio.sleep(0.005)


@pytest.fixture
def db_path():
    """A fresh Postgres schema, pre-seeded with alice/bob (this file's
    own two standard test users) - the local override this file needs
    beyond the shared, unseeded db_path fixture in conftest.py."""
    schema = f"test_{uuid.uuid4().hex}"
    accounts.init_db(schema)
    accounts.register(schema, "alice", "pw")
    accounts.register(schema, "bob", "pw")
    yield schema
    accounts_db.drop_schema(schema)


def _make_shard(accounts_base_url: str, namespace: str = None) -> GameShard:
    return GameShard(
        accounts_client=AccountsClient(accounts_base_url),
        redis_client=get_redis_client(),
        namespace=namespace or uuid.uuid4().hex,
    )


def _host_seat(room_id: str, color: str, username: str, opponent_username: str) -> str:
    return shard_protocol.send_routing_message(
        shard_protocol.HostSeatMessage(room_id=room_id, color=color, username=username, opponent_username=opponent_username)
    )


def test_two_host_seats_for_the_same_room_build_and_start_a_game_room(db_path, accounts_base_url):
    asyncio.run(_host_seat_pairing_scenario(db_path, accounts_base_url))


async def _host_seat_pairing_scenario(db_path, accounts_base_url):
    shard = _make_shard(accounts_base_url)
    white_ws = FakeRelayConnection([_host_seat("r1", WHITE, "alice", "bob")])
    black_ws = FakeRelayConnection([_host_seat("r1", BLACK, "bob", "alice")])

    white_task = asyncio.create_task(shard.handle_connection(white_ws))
    black_task = asyncio.create_task(shard.handle_connection(black_ws))
    await _wait_until(lambda: "r1" in shard._rooms)  # both seats arrived and the room started

    await _wait_until(lambda: protocol.MATCH_FOUND in _sent_types(white_ws))
    await _wait_until(lambda: protocol.MATCH_FOUND in _sent_types(black_ws))
    match_found = next(m for m in white_ws.sent if m["type"] == protocol.MATCH_FOUND)
    assert match_found["color"] == WHITE

    shard._rooms["r1"].stop()
    await white_ws.close()
    await black_ws.close()
    await asyncio.wait_for(white_task, timeout=1)
    await asyncio.wait_for(black_task, timeout=1)


def test_a_move_reaches_the_game_room_through_the_relay_connection(db_path, accounts_base_url):
    asyncio.run(_relayed_move_scenario(db_path, accounts_base_url))


async def _relayed_move_scenario(db_path, accounts_base_url):
    shard = _make_shard(accounts_base_url)
    white_ws = FakeRelayConnection([_host_seat("r1", WHITE, "alice", "bob")])
    black_ws = FakeRelayConnection([_host_seat("r1", BLACK, "bob", "alice")])
    white_task = asyncio.create_task(shard.handle_connection(white_ws))
    black_task = asyncio.create_task(shard.handle_connection(black_ws))
    await _wait_until(lambda: "r1" in shard._rooms)

    room = shard._rooms["r1"]
    white_ws.push(serialize_message(SelectOrMoveMessage(row=6, col=0)))  # select
    white_ws.push(serialize_message(SelectOrMoveMessage(row=5, col=0)))  # move
    await _wait_until(lambda: protocol.PIECE_MOTION_STARTED in _sent_types(black_ws))  # game_room.py's own broadcast, unmodified

    room.stop()
    await white_ws.close()
    await black_ws.close()
    await asyncio.wait_for(white_task, timeout=1)
    await asyncio.wait_for(black_task, timeout=1)


def test_the_other_seat_never_arriving_times_out_and_closes(db_path, accounts_base_url, monkeypatch):
    monkeypatch.setattr(game_shard, "PENDING_ROOM_TIMEOUT_SECONDS", 0.05)
    asyncio.run(_pending_room_timeout_scenario(db_path, accounts_base_url))


async def _pending_room_timeout_scenario(db_path, accounts_base_url):
    shard = _make_shard(accounts_base_url)
    lone_ws = FakeRelayConnection([_host_seat("r1", WHITE, "alice", "bob")])

    await asyncio.wait_for(shard.handle_connection(lone_ws), timeout=1)

    assert lone_ws.closed
    assert "r1" not in shard._rooms


def test_reconnect_to_a_live_room_succeeds(db_path, accounts_base_url):
    asyncio.run(_reconnect_scenario(db_path, accounts_base_url))


async def _reconnect_scenario(db_path, accounts_base_url):
    shard = _make_shard(accounts_base_url)
    white_ws = FakeRelayConnection([_host_seat("r1", WHITE, "alice", "bob")])
    black_ws = FakeRelayConnection([_host_seat("r1", BLACK, "bob", "alice")])
    white_task = asyncio.create_task(shard.handle_connection(white_ws))
    black_task = asyncio.create_task(shard.handle_connection(black_ws))
    await _wait_until(lambda: "r1" in shard._rooms)
    room = shard._rooms["r1"]

    await white_ws.close()  # alice's relay connection drops mid-game
    await asyncio.wait_for(white_task, timeout=1)  # the task's own finally already awaited handle_disconnect
    assert room._disconnected_color == WHITE

    new_white_ws = FakeRelayConnection([
        shard_protocol.send_routing_message(shard_protocol.ReconnectMessage(room_id="r1", color=WHITE, username="alice"))
    ])
    reconnect_task = asyncio.create_task(shard.handle_connection(new_white_ws))
    # try_reconnect clears _disconnected_color synchronously, before its
    # own (awaited, HTTP-round-trip-carrying) sends complete - wait on the
    # actual observable effect, not the internal field, to avoid a race.
    await _wait_until(lambda: protocol.MATCH_FOUND in _sent_types(new_white_ws))
    assert room._disconnected_color is None  # try_reconnect succeeded

    room.stop()
    await new_white_ws.close()
    await black_ws.close()
    await asyncio.wait_for(reconnect_task, timeout=1)
    await asyncio.wait_for(black_task, timeout=1)


def test_reconnect_to_an_unknown_room_closes_with_nothing_sent(db_path, accounts_base_url):
    asyncio.run(_reconnect_unknown_room_scenario(db_path, accounts_base_url))


async def _reconnect_unknown_room_scenario(db_path, accounts_base_url):
    shard = _make_shard(accounts_base_url)
    ws = FakeRelayConnection([
        shard_protocol.send_routing_message(shard_protocol.ReconnectMessage(room_id="nosuch", color=WHITE, username="alice"))
    ])

    await asyncio.wait_for(shard.handle_connection(ws), timeout=1)

    assert ws.closed
    assert ws.sent == []


def test_spectate_a_live_room_gets_an_immediate_snapshot(db_path, accounts_base_url):
    asyncio.run(_spectate_scenario(db_path, accounts_base_url))


async def _spectate_scenario(db_path, accounts_base_url):
    shard = _make_shard(accounts_base_url)
    white_ws = FakeRelayConnection([_host_seat("r1", WHITE, "alice", "bob")])
    black_ws = FakeRelayConnection([_host_seat("r1", BLACK, "bob", "alice")])
    white_task = asyncio.create_task(shard.handle_connection(white_ws))
    black_task = asyncio.create_task(shard.handle_connection(black_ws))
    await _wait_until(lambda: "r1" in shard._rooms)
    room = shard._rooms["r1"]

    spectator_ws = FakeRelayConnection([
        shard_protocol.send_routing_message(shard_protocol.SpectateMessage(room_id="r1", username="carol"))
    ])
    spectate_task = asyncio.create_task(shard.handle_connection(spectator_ws))
    await _wait_until(lambda: protocol.STATE in _sent_types(spectator_ws))

    assert spectator_ws in room._spectators

    room.stop()
    await white_ws.close()
    await black_ws.close()
    await spectator_ws.close()
    await asyncio.wait_for(white_task, timeout=1)
    await asyncio.wait_for(black_task, timeout=1)
    await asyncio.wait_for(spectate_task, timeout=1)


def test_spectate_an_unknown_room_closes_with_nothing_sent(db_path, accounts_base_url):
    asyncio.run(_spectate_unknown_room_scenario(db_path, accounts_base_url))


async def _spectate_unknown_room_scenario(db_path, accounts_base_url):
    shard = _make_shard(accounts_base_url)
    ws = FakeRelayConnection([shard_protocol.send_routing_message(shard_protocol.SpectateMessage(room_id="nosuch", username="carol"))])

    await asyncio.wait_for(shard.handle_connection(ws), timeout=1)

    assert ws.closed
    assert ws.sent == []


def test_leaving_after_game_over_releases_the_room_and_kicks_the_other_seat(db_path, accounts_base_url):
    asyncio.run(_leave_room_scenario(db_path, accounts_base_url))


async def _leave_room_scenario(db_path, accounts_base_url):
    shard = _make_shard(accounts_base_url)
    white_ws = FakeRelayConnection([_host_seat("r1", WHITE, "alice", "bob")])
    black_ws = FakeRelayConnection([_host_seat("r1", BLACK, "bob", "alice")])
    white_task = asyncio.create_task(shard.handle_connection(white_ws))
    black_task = asyncio.create_task(shard.handle_connection(black_ws))
    await _wait_until(lambda: "r1" in shard._rooms)
    room = shard._rooms["r1"]
    room._engine.resign()  # force game-over, same trick test_game_room.py uses

    white_ws.push(serialize_message(LeaveRoomMessage()))
    await _wait_until(lambda: protocol.LEFT_ROOM in _sent_types(black_ws))

    assert protocol.LEFT_ROOM in _sent_types(white_ws)
    assert "r1" not in shard._rooms  # on_game_over -> _release_room already ran
    assert black_ws.closed  # the kicked-back-to-lobby signal ws_gateway.py relies on

    await asyncio.wait_for(white_task, timeout=1)
    await asyncio.wait_for(black_task, timeout=1)

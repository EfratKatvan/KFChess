from __future__ import annotations

import asyncio
import uuid

from kungfu_chess.model.piece import WHITE, BLACK
from kungfu_chess.model.game_state import MoveLoggedEvent
from kungfu_chess.model.position import Position
from kungfu_chess.server import accounts
from kungfu_chess.server.accounts_client import AccountsClient
from kungfu_chess.server.game_room import GameRoom
from kungfu_chess.server.messages import SelectOrMoveMessage
from kungfu_chess.server.move_log_stream import MoveLogStream
from tests.unit.test_matchmaker import FakeConnection

"""Server_Design.md section 3's own open question - "JetStream replay
correctness under real load ... not yet verified against a real
crash-and-replay test" - is exactly what this file verifies: a real
NATS JetStream instance, not a mock (the same standard every other
infra dependency in this suite is already held to), publishing and
replaying real moves."""


def _room_id() -> str:
    return f"test_{uuid.uuid4().hex}"


async def _new_stream() -> MoveLogStream:
    return await MoveLogStream.connect()


def test_replaying_a_room_with_no_history_is_a_no_op():
    asyncio.run(_empty_replay_scenario())


async def _empty_replay_scenario():
    stream = await _new_stream()
    replayed = await stream.replay_moves(_room_id())
    assert replayed == []
    await stream.close()


def test_publish_then_replay_round_trips_every_move_in_order():
    asyncio.run(_publish_replay_scenario())


async def _publish_replay_scenario():
    stream = await _new_stream()
    room_id = _room_id()
    first = MoveLoggedEvent(WHITE, Position(6, 0), Position(5, 0), "pawn", False, 0, duration_ms=500)
    second = MoveLoggedEvent(BLACK, Position(1, 0), Position(2, 0), "pawn", False, 800, duration_ms=500)

    await stream.publish_move(room_id, first)
    await stream.publish_move(room_id, second)
    replayed = await stream.replay_moves(room_id)

    assert len(replayed) == 2
    (event_a, published_a), (event_b, published_b) = replayed
    assert (event_a.color, event_a.from_pos, event_a.to_pos) == (WHITE, Position(6, 0), Position(5, 0))
    assert (event_b.color, event_b.from_pos, event_b.to_pos) == (BLACK, Position(1, 0), Position(2, 0))
    assert published_a > 0 and published_b >= published_a  # real wall-clock timestamps, in publish order
    await stream.close()


def test_reset_room_discards_history_so_a_later_replay_is_empty():
    asyncio.run(_reset_scenario())


async def _reset_scenario():
    stream = await _new_stream()
    room_id = _room_id()
    await stream.publish_move(room_id, MoveLoggedEvent(WHITE, Position(6, 0), Position(5, 0), "pawn", False, 0))

    await stream.reset_room(room_id)

    assert await stream.replay_moves(room_id) == []
    await stream.close()


def test_reset_room_with_no_prior_history_is_a_no_op():
    asyncio.run(_reset_no_history_scenario())


async def _reset_no_history_scenario():
    stream = await _new_stream()
    await stream.reset_room(_room_id())  # must not raise
    await stream.close()


def test_replaying_a_room_reconstructs_the_same_piece_positions_a_live_room_reached(db_path, accounts_base_url):
    """The actual crash-recovery claim (Server_Design.md sections 3,
    20.5): build a room, play it live for a couple of moves, then - as
    if this were a *different* Shard process recovering after a crash -
    build a brand-new GameRoom for the same room_id from scratch and
    replay its recorded history into it. The two must agree on where
    every piece ended up, without the second room ever having witnessed
    a single live message."""
    asyncio.run(_replay_reconstruction_scenario(db_path, accounts_base_url))


async def _replay_reconstruction_scenario(db_path, accounts_base_url):
    accounts.register(db_path, "white_player", "pw")
    accounts.register(db_path, "black_player", "pw")
    stream = await _new_stream()
    room_id = _room_id()

    live_room = GameRoom(
        FakeConnection("white"), "white_player", FakeConnection("black"), "black_player",
        accounts_client=AccountsClient(accounts_base_url), room_id=room_id, move_log_stream=stream,
    )
    await live_room.handle_message(WHITE, SelectOrMoveMessage(row=6, col=0))  # select white pawn
    await live_room.handle_message(WHITE, SelectOrMoveMessage(row=5, col=0))  # move it forward
    await live_room.handle_message(BLACK, SelectOrMoveMessage(row=1, col=0))  # select black pawn
    await live_room.handle_message(BLACK, SelectOrMoveMessage(row=2, col=0))  # move it forward
    # live_room.start() was never called (no real tick loop here), so its
    # own motions would otherwise still be reported mid-flight rather
    # than arrived - advance its engine directly, comfortably past any
    # one-square pawn's travel time, for a fair comparison against the
    # recovered room below (whose own replay() does its own time
    # advancement as part of reconstructing state).
    live_room._engine.wait(2000)
    await asyncio.sleep(0.2)  # let the fire-and-forget JetStream publishes actually land

    recovered_room = GameRoom(
        FakeConnection("white-recovered"), "white_player", FakeConnection("black-recovered"), "black_player",
        accounts_client=AccountsClient(accounts_base_url), room_id=room_id, move_log_stream=stream,
    )
    replayed = await stream.replay_moves(room_id)
    assert len(replayed) == 2  # both moves actually made it to JetStream
    recovered_room.replay(replayed)

    live_positions = {p.position for p in live_room._engine.snapshot().pieces}
    recovered_positions = {p.position for p in recovered_room._engine.snapshot().pieces}
    assert recovered_positions == live_positions
    assert Position(5, 0) in recovered_positions  # white pawn actually reached its destination
    assert Position(2, 0) in recovered_positions  # black pawn actually reached its destination
    assert Position(6, 0) not in recovered_positions  # and isn't still sitting at its origin square

    await stream.close()

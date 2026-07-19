import asyncio

from kungfu_chess.model.piece import WHITE, BLACK
from kungfu_chess.server import protocol
from kungfu_chess.server.game_room import GameRoom
from tests.unit.test_matchmaker import FakeConnection, _last_type


def test_match_found_sent_to_both_connections_on_start():
    asyncio.run(_start_scenario())


async def _start_scenario():
    white_ws, black_ws = FakeConnection("white"), FakeConnection("black")
    room = GameRoom(white_ws, black_ws)

    await room.start()

    assert _last_type(white_ws) == protocol.MATCH_FOUND
    assert white_ws.sent[-1]["color"] == WHITE
    assert _last_type(black_ws) == protocol.MATCH_FOUND
    assert black_ws.sent[-1]["color"] == BLACK

    room.stop()


def test_white_cannot_move_a_black_piece_through_the_room():
    asyncio.run(_gating_scenario())


async def _gating_scenario():
    white_ws, black_ws = FakeConnection("white"), FakeConnection("black")
    room = GameRoom(white_ws, black_ws)
    await room.start()

    # A black pawn starts at row 1 in the standard starting position - white shouldn't be able to select it.
    await room.handle_message(WHITE, {"type": protocol.SELECT_OR_MOVE, "row": 1, "col": 0})
    assert room._controllers[WHITE].selected_pos is None

    await room.handle_message(BLACK, {"type": protocol.SELECT_OR_MOVE, "row": 1, "col": 0})
    assert room._controllers[BLACK].selected_pos is not None

    room.stop()

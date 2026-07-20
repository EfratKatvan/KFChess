import asyncio

import pytest

from kungfu_chess.engine.board_view_state import BoardViewState, PieceView
from kungfu_chess.model.piece import KING, WHITE, BLACK
from kungfu_chess.model.position import Position
from kungfu_chess.server import accounts, protocol
from kungfu_chess.server.game_room import GameRoom
from kungfu_chess.server.messages import SelectOrMoveMessage
from tests.unit.test_matchmaker import FakeConnection, _last_type


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test_users.db")
    accounts.init_db(path)
    return path


def _view_state_with_survivor(color: str) -> BoardViewState:
    """A minimal game_over=True snapshot where only `color`'s king is
    still on the board - exactly what _apply_rating_update reads to
    decide who won."""
    return BoardViewState(
        width=8, height=8, game_over=True,
        pieces=(PieceView(position=Position(0, 4), color=color, kind=KING, visual_state="idle", elapsed_ms=0),),
    )


def test_match_found_sent_to_both_connections_on_start(db_path):
    asyncio.run(_start_scenario(db_path))


async def _start_scenario(db_path):
    white_ws, black_ws = FakeConnection("white"), FakeConnection("black")
    room = GameRoom(white_ws, "white_player", black_ws, "black_player", db_path=db_path)

    await room.start()

    assert _last_type(white_ws) == protocol.MATCH_FOUND
    assert white_ws.sent[-1]["color"] == WHITE
    assert _last_type(black_ws) == protocol.MATCH_FOUND
    assert black_ws.sent[-1]["color"] == BLACK

    room.stop()


def test_white_cannot_move_a_black_piece_through_the_room(db_path):
    asyncio.run(_gating_scenario(db_path))


async def _gating_scenario(db_path):
    white_ws, black_ws = FakeConnection("white"), FakeConnection("black")
    room = GameRoom(white_ws, "white_player", black_ws, "black_player", db_path=db_path)
    await room.start()

    # A black pawn starts at row 1 in the standard starting position - white shouldn't be able to select it.
    await room.handle_message(WHITE, SelectOrMoveMessage(row=1, col=0))
    assert room._controllers[WHITE].selected_pos is None

    await room.handle_message(BLACK, SelectOrMoveMessage(row=1, col=0))
    assert room._controllers[BLACK].selected_pos is not None

    room.stop()


def test_apply_rating_update_credits_the_survivors_color_as_the_winner(db_path):
    asyncio.run(_rating_update_scenario(db_path))


async def _rating_update_scenario(db_path):
    accounts.authenticate(db_path, "white_player", "pw")
    accounts.authenticate(db_path, "black_player", "pw")

    white_ws, black_ws = FakeConnection("white"), FakeConnection("black")
    room = GameRoom(white_ws, "white_player", black_ws, "black_player", db_path=db_path)
    await room.start()

    room._apply_rating_update(_view_state_with_survivor(WHITE))  # only white's king survives

    assert accounts.get_rating(db_path, "white_player") == accounts.STARTING_RATING + accounts.ELO_K_FACTOR // 2
    assert accounts.get_rating(db_path, "black_player") == accounts.STARTING_RATING - accounts.ELO_K_FACTOR // 2

    room.stop()


def test_apply_rating_update_only_ever_applies_once_per_game(db_path):
    asyncio.run(_rating_update_once_scenario(db_path))


async def _rating_update_once_scenario(db_path):
    accounts.authenticate(db_path, "white_player", "pw")
    accounts.authenticate(db_path, "black_player", "pw")

    white_ws, black_ws = FakeConnection("white"), FakeConnection("black")
    room = GameRoom(white_ws, "white_player", black_ws, "black_player", db_path=db_path)
    await room.start()

    view_state = _view_state_with_survivor(WHITE)
    room._apply_rating_update(view_state)
    rating_after_first_call = accounts.get_rating(db_path, "white_player")

    room._apply_rating_update(view_state)  # a second call must be a no-op (_rating_update_applied guard)
    rating_after_second_call = accounts.get_rating(db_path, "white_player")

    assert rating_after_first_call == rating_after_second_call

    room.stop()

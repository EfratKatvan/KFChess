from kungfu_chess.model.board import Board
from kungfu_chess.model.game_state import GameState


def test_game_state_starts_not_over_by_default():
    state = GameState(board=Board(width=1, height=1))
    assert state.game_over is False


def test_game_state_holds_the_board():
    board = Board(width=3, height=2)
    state = GameState(board=board)
    assert state.board is board


def test_game_state_game_over_can_be_set_true():
    state = GameState(board=Board(width=1, height=1))
    state.game_over = True
    assert state.game_over is True

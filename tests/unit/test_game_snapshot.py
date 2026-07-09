from kungfu_chess.model.board import Board
from kungfu_chess.model.game_snapshot import GameSnapshot


def test_game_snapshot_holds_board_and_game_over():
    board = Board(width=2, height=2)
    snapshot = GameSnapshot(board=board, game_over=True)
    assert snapshot.board is board
    assert snapshot.game_over is True


def test_game_snapshot_is_frozen():
    snapshot = GameSnapshot(board=Board(width=1, height=1), game_over=False)
    try:
        snapshot.game_over = True
        assert False, "GameSnapshot should be immutable"
    except AttributeError:
        pass

from board.model import Board


def test_width_and_height():
    board = Board.from_rows([["wK", ".", "bK"], [".", ".", "."]])
    assert board.height == 2
    assert board.width == 3


def test_empty_board_dimensions():
    board = Board.from_rows([])
    assert board.height == 0
    assert board.width == 0


def test_to_canonical_lines():
    board = Board.from_rows([["wK", ".", "bK"], [".", ".", "."]])
    assert board.to_canonical_lines() == ["wK . bK", ". . ."]
from kungfu_chess.model.board import Board
from kungfu_chess.model.position import Position
from kungfu_chess.input.board_mapper import BoardMapper


def test_pixel_maps_to_expected_cell():
    board = Board(width=2, height=2)
    mapper = BoardMapper(board)
    assert mapper.to_cell(50, 50) == Position(0, 0)
    assert mapper.to_cell(150, 50) == Position(0, 1)
    assert mapper.to_cell(50, 150) == Position(1, 0)


def test_pixel_outside_board_returns_none():
    board = Board(width=2, height=1)
    mapper = BoardMapper(board)
    assert mapper.to_cell(-10, 50) is None
    assert mapper.to_cell(50, 250) is None


def test_custom_cell_size_is_respected():
    board = Board(width=2, height=1)
    mapper = BoardMapper(board, cell_size=50)
    assert mapper.to_cell(60, 10) == Position(0, 1)

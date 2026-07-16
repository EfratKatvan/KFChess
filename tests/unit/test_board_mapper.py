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


def test_y_offset_shifts_the_board_down_before_mapping_to_a_row():
    board = Board(width=1, height=2)
    mapper = BoardMapper(board, y_offset=60)

    assert mapper.to_cell(50, 60) == Position(0, 0)
    assert mapper.to_cell(50, 159) == Position(0, 0)
    assert mapper.to_cell(50, 160) == Position(1, 0)


def test_click_above_the_y_offset_maps_to_no_cell():
    board = Board(width=1, height=1)
    mapper = BoardMapper(board, y_offset=60)

    assert mapper.to_cell(50, 30) is None


def test_x_offset_shifts_the_board_right_before_mapping_to_a_column():
    """Mirrors the y_offset shift, but horizontally - matches the side
    panel the renderer draws left of the board (see
    view/renderer.py:SIDE_PANEL_WIDTH)."""
    board = Board(width=2, height=1)
    mapper = BoardMapper(board, x_offset=220)

    assert mapper.to_cell(220, 50) == Position(0, 0)
    assert mapper.to_cell(319, 50) == Position(0, 0)
    assert mapper.to_cell(320, 50) == Position(0, 1)


def test_click_left_of_the_x_offset_maps_to_no_cell():
    board = Board(width=1, height=1)
    mapper = BoardMapper(board, x_offset=220)

    assert mapper.to_cell(100, 50) is None


def test_x_offset_and_y_offset_combine():
    board = Board(width=2, height=2)
    mapper = BoardMapper(board, x_offset=220, y_offset=60)

    assert mapper.to_cell(220, 60) == Position(0, 0)
    assert mapper.to_cell(320, 160) == Position(1, 1)
    assert mapper.to_cell(50, 60) is None   # left of x_offset
    assert mapper.to_cell(220, 30) is None  # above y_offset

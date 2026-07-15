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
    """מקביל להזחת הלוח ב-HUD_HEIGHT פיקסלים ברנדרר (ר' view/renderer.py) -
    קליק שנראה כאילו הוא בשורה 0 (מתחת לרצועת ה-HUD) חייב למפות לשורה 0,
    לא לשורה 1."""
    board = Board(width=1, height=2)
    mapper = BoardMapper(board, y_offset=60)

    assert mapper.to_cell(50, 60) == Position(0, 0)
    assert mapper.to_cell(50, 159) == Position(0, 0)
    assert mapper.to_cell(50, 160) == Position(1, 0)


def test_click_inside_the_hud_strip_maps_to_no_cell():
    board = Board(width=1, height=1)
    mapper = BoardMapper(board, y_offset=60)

    assert mapper.to_cell(50, 30) is None

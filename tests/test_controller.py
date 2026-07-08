import pytest
from board.model import Board
from game.controller import GameController


@pytest.fixture
def sample_board():
    # לוח 3x3 לדוגמה
    rows = [
        ["wR", ".", "bP"],
        [".", "wP", "."],
        [".", ".", "bK"],
    ]
    return Board.from_rows(rows)


def test_click_outside_board(sample_board):
    controller = GameController(sample_board)
    # לחיצה מחוץ לגבולות הלוח (למשל x=-10, y=50 או x=500, y=500)
    controller.handle_click(-10, 50)
    assert controller.selected_pos is None

    controller.handle_click(500, 500)
    assert controller.selected_pos is None


def test_click_empty_cell_no_selection(sample_board):
    controller = GameController(sample_board)
    # תא (0, 1) הוא ריק (x=150, y=50)
    controller.handle_click(150, 50)
    assert controller.selected_pos is None


def test_select_piece(sample_board):
    controller = GameController(sample_board)
    # תא (0, 0) מכיל wR (x=50, y=50)
    controller.handle_click(50, 50)
    assert controller.selected_pos == (0, 0)


def test_change_selection_to_another_piece(sample_board):
    controller = GameController(sample_board)
    # בחר ב-wR ב-(0, 0)
    controller.handle_click(50, 50)
    assert controller.selected_pos == (0, 0)

    # לחץ על wP ב-(1, 1) -> (x=150, y=150)
    controller.handle_click(150, 150)
    assert controller.selected_pos == (1, 1)


def test_move_piece_to_empty_cell(sample_board):
    controller = GameController(sample_board)
    # בחר ב-wR ב-(0, 0)
    controller.handle_click(50, 50)

    # הזיז לתא הריק ב-(0, 1) -> (x=150, y=50)
    controller.handle_click(150, 50)

    # הבחירה צריכה להתאפס
    assert controller.selected_pos is None
    # המקור צריך להיות ריק, היעד צריך להכיל wR
    assert controller.board.get_cell(0, 0) == "."
    assert controller.board.get_cell(0, 1) == "wR"


def test_wait_command(sample_board):
    controller = GameController(sample_board)
    assert controller.clock_ms == 0

    controller.execute_command("wait 500")
    assert controller.clock_ms == 500

    controller.execute_command("wait 300")
    assert controller.clock_ms == 800
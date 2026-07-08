import pytest
from board.model import Board
from game.controller import GameController, is_legal_piece_move


# ==========================================
# טסטים מאיטרציה 1 & 2 (התנהגות בסיסית של Controller)
# ==========================================

def test_click_outside_board():
    board = Board.from_rows([["wK", "."], [".", "."]])
    controller = GameController(board)
    controller.execute_command("click 500 500")
    assert controller.selected_pos is None


def test_click_empty_cell_no_selection():
    board = Board.from_rows([["wK", "."], [".", "."]])
    controller = GameController(board)
    controller.execute_command("click 150 50")  # (0,1) ריקה
    assert controller.selected_pos is None


def test_select_piece():
    board = Board.from_rows([["wK", "."], [".", "."]])
    controller = GameController(board)
    controller.execute_command("click 50 50")  # (0,0)
    assert controller.selected_pos == (0, 0)


def test_change_selection_to_another_piece():
    board = Board.from_rows([["wK", "wR"], [".", "."]])
    controller = GameController(board)
    controller.execute_command("click 50 50")   # בחירת wK
    assert controller.selected_pos == (0, 0)
    controller.execute_command("click 150 50")  # מעבר ל-wR
    assert controller.selected_pos == (0, 1)


def test_click_same_selected_piece_keeps_selection():
    board = Board.from_rows([["wK", "."], [".", "."]])
    controller = GameController(board)
    controller.execute_command("click 50 50")
    assert controller.selected_pos == (0, 0)
    controller.execute_command("click 50 50")
    assert controller.selected_pos == (0, 0)


# ==========================================
# טסטים מאיטרציה 3 (חוקי תנועה של הכלים)
# ==========================================

def test_king_movement_rules():
    assert is_legal_piece_move("K", (1, 1), (1, 2)) is True
    assert is_legal_piece_move("K", (1, 1), (2, 2)) is True
    assert is_legal_piece_move("K", (1, 1), (1, 3)) is False


def test_rook_movement_rules():
    assert is_legal_piece_move("R", (0, 0), (0, 3)) is True
    assert is_legal_piece_move("R", (0, 0), (3, 0)) is True
    assert is_legal_piece_move("R", (0, 0), (2, 2)) is False


def test_bishop_movement_rules():
    assert is_legal_piece_move("B", (0, 0), (3, 3)) is True
    assert is_legal_piece_move("B", (0, 0), (0, 2)) is False


def test_queen_movement_rules():
    assert is_legal_piece_move("Q", (0, 0), (0, 2)) is True
    assert is_legal_piece_move("Q", (0, 0), (2, 2)) is True
    assert is_legal_piece_move("Q", (0, 0), (1, 2)) is False


def test_knight_movement_rules():
    assert is_legal_piece_move("N", (0, 0), (2, 1)) is True
    assert is_legal_piece_move("N", (0, 0), (1, 2)) is True
    assert is_legal_piece_move("N", (0, 0), (2, 2)) is False


def test_controller_valid_piece_move_updates_board():
    board = Board.from_rows([
        ["wR", ".", "."],
        [".", ".", "."]
    ])
    controller = GameController(board)

    controller.execute_command("click 50 50")   # בחירת הצריח ב-(0,0)
    controller.execute_command("click 250 50")  # תנועה ל-(0,2)

    assert controller.selected_pos is None
    assert board._rows[0] == [".", ".", "wR"]


def test_controller_invalid_piece_move_ignored():
    board = Board.from_rows([
        ["wR", ".", "."],
        [".", ".", "."]
    ])
    controller = GameController(board)

    controller.execute_command("click 50 50")   # בחירת הצריח
    controller.execute_command("click 150 150") # ניסיון תנועה באלכסון (לא חוקי)

    # הצריח נשאר במקומו והלוח לא משתנה
    assert board._rows[0][0] == "wR"
    assert board._rows[1][1] == "."

# ==========================================
# טסטים מאיטרציה 4 (חסימות ואכילה)
# ==========================================

def test_rook_blocked_by_piece():
    board = Board.from_rows([
        ["wR", "wP", "."],
        [".", ".", "."]
    ])
    controller = GameController(board)
    controller.execute_command("click 50 50")   # בחירת הצריח ב-(0,0)
    controller.execute_command("click 250 50")  # ניסיון תנועה ל-(0,2) - חסום!

    assert board._rows[0][0] == "wR"
    assert board._rows[0][2] == "."


def test_knight_jumps_over_blockers():
    board = Board.from_rows([
        ["wN", "wP", "."],
        ["wP", "wP", "."],
        [".", ".", "."]
    ])
    controller = GameController(board)
    controller.execute_command("click 50 50")   # בחירת הפרש ב-(0,0)
    controller.execute_command("click 150 250") # תנועה בצורת L ל-(2,1) - קופץ מעל חסמים!

    assert controller.selected_pos is None
    assert board._rows[0][0] == "."
    assert board._rows[2][1] == "wN"


def test_capture_enemy_piece():
    board = Board.from_rows([
        ["wR", ".", "bR"],
        [".", ".", "."]
    ])
    controller = GameController(board)
    controller.execute_command("click 50 50")   # בחירת הצריח הלבן ב-(0,0)
    controller.execute_command("click 250 50")  # אכילת הצריח השחור ב-(0,2)

    assert controller.selected_pos is None
    assert board._rows[0][0] == "."
    assert board._rows[0][2] == "wR"


def test_cannot_capture_own_piece():
    board = Board.from_rows([
        ["wR", ".", "wK"],
        [".", ".", "."]
    ])
    controller = GameController(board)
    controller.execute_command("click 50 50")   # בחירת wR
    controller.execute_command("click 250 50")  # לחיצה על wK (אותו צבע) -> משנה בחירה ל-wK

    assert controller.selected_pos == (0, 2)
    assert board._rows[0][0] == "wR"
    assert board._rows[0][2] == "wK"
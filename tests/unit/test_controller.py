from kungfu_chess.model.board import Board
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.input.controller import Controller


def make_controller(board: Board) -> Controller:
    rule_engine = RuleEngine(board)
    arbiter = RealTimeArbiter(board)
    engine = GameEngine(board, rule_engine, arbiter)
    mapper = BoardMapper(board)
    return Controller(mapper, engine)


# ==========================================
# לחיצות, בחירת כלים ושינוי בחירה
# ==========================================

def test_click_outside_board():
    board = Board.from_rows([["wR", "."]])
    controller = make_controller(board)
    controller.handle_click(-10, 50)
    assert controller.selected_pos is None


def test_click_empty_cell_no_selection():
    board = Board.from_rows([["."]])
    controller = make_controller(board)
    controller.handle_click(50, 50)
    assert controller.selected_pos is None


def test_select_piece():
    board = Board.from_rows([["wR"]])
    controller = make_controller(board)
    controller.handle_click(50, 50)
    assert controller.selected_pos == (0, 0)


def test_change_selection_to_another_piece():
    board = Board.from_rows([["wR", "wB"]])
    controller = make_controller(board)
    controller.handle_click(50, 50)   # בחירת wR
    controller.handle_click(150, 50)  # שינוי בחירה ל-wB
    assert controller.selected_pos == (0, 1)


def test_click_same_selected_piece_keeps_selection():
    board = Board.from_rows([["wR"]])
    controller = make_controller(board)
    controller.handle_click(50, 50)
    controller.handle_click(50, 50)
    assert controller.selected_pos == (0, 0)


# ==========================================
# מהלכים לא חוקיים - הבחירה נשארת ללא שינוי, הלוח לא זז
# ==========================================

def test_invalid_piece_move_keeps_selection_and_board_unchanged():
    board = Board.from_rows([["wR", ".", "."], [".", ".", "."]])
    controller = make_controller(board)

    controller.handle_click(50, 50)   # בחירת wR ב-(0,0)
    controller.handle_click(150, 150)  # תנועה לא חוקית באלכסון

    assert controller.selected_pos == (0, 0)
    assert board.get_cell(0, 0) == "wR"


def test_rook_blocked_by_piece_keeps_selection():
    board = Board.from_rows([["wR", "wP", "."], [".", ".", "."]])
    controller = make_controller(board)

    controller.handle_click(50, 50)   # בחירת wR ב-(0,0)
    controller.handle_click(250, 50)  # ניסיון לא חוקי לדלג מעל wP

    assert controller.selected_pos == (0, 0)
    assert board.get_cell(0, 1) == "wP"


def test_cannot_capture_own_piece_reselects_it_instead():
    board = Board.from_rows([["wR", ".", "wB"]])
    controller = make_controller(board)

    controller.handle_click(50, 50)   # בחירת wR ב-(0,0)
    controller.handle_click(250, 50)  # ניסיון אכילה של כלי ידידותי -> בוחר אותו

    assert controller.selected_pos == (0, 2)
    assert board.get_cell(0, 0) == "wR"
    assert board.get_cell(0, 2) == "wB"


# ==========================================
# התחלת מהלך חוקי - הבחירה מתאפסת מיד, אבל הלוח משתנה רק אחרי wait
# ==========================================

def test_legal_move_clears_selection_immediately_but_does_not_move_piece_yet():
    board = Board.from_rows([["wR", ".", "."]])
    controller = make_controller(board)

    controller.handle_click(50, 50)
    controller.handle_click(250, 50)

    assert controller.selected_pos is None
    assert board.get_cell(0, 0) == "wR"
    assert board.get_cell(0, 2) == "."


def test_piece_mid_motion_cannot_be_reselected():
    board = Board.from_rows([["wR", ".", ".", "."]])
    controller = make_controller(board)

    controller.handle_click(50, 50)   # בחירת wR
    controller.handle_click(350, 50)  # התחלת תנועה ל-(0,3)

    controller.handle_click(50, 50)   # ניסיון לבחור מחדש את (0,0) בזמן שהכלי בתנועה
    assert controller.selected_pos is None

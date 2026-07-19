from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import WHITE
from kungfu_chess.io.board_parser import build_board
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.input.controller import Controller


def make_stack(rows):
    board = build_board(rows)
    rule_engine = RuleEngine(board)
    arbiter = RealTimeArbiter(board)
    engine = GameEngine(board, rule_engine, arbiter)
    mapper = BoardMapper(board)
    controller = Controller(mapper, engine)
    return board, controller, engine


def make_controller(rows) -> Controller:
    _, controller, _ = make_stack(rows)
    return controller


# ==========================================
# לחיצות, בחירת כלים ושינוי בחירה
# ==========================================

def test_click_outside_board():
    controller = make_controller([["wR", "."]])
    controller.handle_click(-10, 50)
    assert controller.selected_pos is None


def test_click_empty_cell_no_selection():
    controller = make_controller([["."]])
    controller.handle_click(50, 50)
    assert controller.selected_pos is None


def test_select_piece():
    controller = make_controller([["wR"]])
    controller.handle_click(50, 50)
    assert controller.selected_pos == Position(0, 0)


def test_change_selection_to_another_piece():
    controller = make_controller([["wR", "wB"]])
    controller.handle_click(50, 50)   # בחירת wR
    controller.handle_click(150, 50)  # שינוי בחירה ל-wB
    assert controller.selected_pos == Position(0, 1)


def test_click_same_selected_piece_keeps_selection():
    controller = make_controller([["wR"]])
    controller.handle_click(50, 50)
    controller.handle_click(50, 50)
    assert controller.selected_pos == Position(0, 0)


# ==========================================
# מהלכים לא חוקיים - הבחירה נשארת ללא שינוי, הלוח לא זז
# ==========================================

def test_invalid_piece_move_keeps_selection_and_board_unchanged():
    board, controller, _ = make_stack([["wR", ".", "."], [".", ".", "."]])

    controller.handle_click(50, 50)   # בחירת wR ב-(0,0)
    controller.handle_click(150, 150)  # תנועה לא חוקית באלכסון

    assert controller.selected_pos == Position(0, 0)
    assert board.piece_at(Position(0, 0)) is not None


def test_rook_blocked_by_piece_keeps_selection():
    board, controller, _ = make_stack([["wR", "wP", "."], [".", ".", "."]])

    controller.handle_click(50, 50)   # בחירת wR ב-(0,0)
    controller.handle_click(250, 50)  # ניסיון לא חוקי לדלג מעל wP

    assert controller.selected_pos == Position(0, 0)
    assert board.piece_at(Position(0, 1)) is not None


def test_cannot_capture_own_piece_reselects_it_instead():
    board, controller, _ = make_stack([["wR", ".", "wB"]])

    controller.handle_click(50, 50)   # בחירת wR ב-(0,0)
    controller.handle_click(250, 50)  # ניסיון אכילה של כלי ידידותי -> בוחר אותו

    assert controller.selected_pos == Position(0, 2)
    assert board.piece_at(Position(0, 0)) is not None
    assert board.piece_at(Position(0, 2)) is not None


# ==========================================
# התחלת מהלך חוקי - הבחירה מתאפסת מיד, אבל הלוח משתנה רק אחרי wait
# ==========================================

def test_legal_move_clears_selection_immediately_but_does_not_move_piece_yet():
    board, controller, _ = make_stack([["wR", ".", "."]])

    controller.handle_click(50, 50)
    controller.handle_click(250, 50)

    assert controller.selected_pos is None
    assert board.piece_at(Position(0, 0)) is not None
    assert board.piece_at(Position(0, 2)) is None


def test_piece_mid_motion_cannot_be_reselected():
    _, controller, _ = make_stack([["wR", ".", ".", "."]])

    controller.handle_click(50, 50)   # בחירת wR
    controller.handle_click(350, 50)  # התחלת תנועה ל-(0,3)

    controller.handle_click(50, 50)   # ניסיון לבחור מחדש את (0,0) בזמן שהכלי בתנועה
    assert controller.selected_pos is None


# ==========================================
# אחרי סיום המשחק - קליקים לא אמורים לשנות בחירה בכלל
# ==========================================

def test_click_does_not_select_a_piece_after_game_over():
    _, controller, engine = make_stack([["wR", "bK"]])

    controller.handle_click(50, 50)   # בחירת wR ב-(0,0)
    controller.handle_click(150, 50)  # wR אוכל את bK ב-(0,1)
    engine.wait(1000)
    assert engine.is_game_over() is True

    controller.handle_click(50, 50)   # ניסיון לבחור כלי אחרי סיום המשחק
    assert controller.selected_pos is None


# ==========================================
# owner_color - a networked player can only select/jump their own color.
# None (the default, used by every test above) keeps single-player behavior.
# ==========================================

def test_owner_color_none_keeps_ungated_single_player_behavior():
    board, _, engine = make_stack([["wR", "bR"]])
    controller = Controller(BoardMapper(board), engine, owner_color=None)
    controller.handle_click(150, 50)  # bR - no owner restriction
    assert controller.selected_pos == Position(0, 1)


def test_owner_cannot_select_opponents_piece():
    board, _, engine = make_stack([["wR", "bR"]])
    controller = Controller(BoardMapper(board), engine, owner_color=WHITE)
    controller.handle_click(150, 50)  # bR belongs to black
    assert controller.selected_pos is None


def test_owner_can_select_own_piece():
    board, _, engine = make_stack([["wR", "bR"]])
    controller = Controller(BoardMapper(board), engine, owner_color=WHITE)
    controller.handle_click(50, 50)  # wR belongs to white
    assert controller.selected_pos == Position(0, 0)


def test_owner_cannot_jump_opponents_piece():
    board, _, engine = make_stack([["wR", "bR"]])
    controller = Controller(BoardMapper(board), engine, owner_color=WHITE)
    controller.handle_jump(150, 50)  # bR - gate should block this before it reaches the engine
    assert engine.try_jump(Position(0, 1)) is True  # still free to jump - the earlier attempt never started


def test_owner_can_jump_own_piece():
    board, _, engine = make_stack([["wR", "bR"]])
    controller = Controller(BoardMapper(board), engine, owner_color=WHITE)
    controller.handle_jump(50, 50)  # wR belongs to white
    assert engine.try_jump(Position(0, 0)) is False  # already airborne from the controller's jump

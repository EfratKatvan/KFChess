from kungfu_chess.model.board import Board
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.input.controller import Controller


def make_stack(board: Board):
    rule_engine = RuleEngine(board)
    arbiter = RealTimeArbiter(board)
    engine = GameEngine(board, rule_engine, arbiter)
    mapper = BoardMapper(board)
    controller = Controller(mapper, engine)
    return controller, engine, arbiter


# ==========================================
# שאילתות בסיסיות שה-Controller נשען עליהן (has_piece / is_same_color)
# ==========================================

def test_has_piece_true_for_occupied_cell():
    board = Board.from_rows([["wR", "."]])
    _, engine, _ = make_stack(board)
    assert engine.has_piece(0, 0) is True
    assert engine.has_piece(0, 1) is False


def test_is_same_color_true_for_two_friendly_pieces():
    board = Board.from_rows([["wR", "wB"]])
    _, engine, _ = make_stack(board)
    assert engine.is_same_color((0, 0), (0, 1)) is True


def test_is_same_color_false_for_enemy_pieces():
    board = Board.from_rows([["wR", "bB"]])
    _, engine, _ = make_stack(board)
    assert engine.is_same_color((0, 0), (0, 1)) is False


def test_is_same_color_false_when_either_cell_is_empty():
    board = Board.from_rows([["wR", "."]])
    _, engine, _ = make_stack(board)
    assert engine.is_same_color((0, 0), (0, 1)) is False


def test_try_move_looks_up_the_piece_token_itself():
    board = Board.from_rows([["wR", ".", "."]])
    _, engine, _ = make_stack(board)
    result = engine.try_move((0, 0), (0, 2))
    assert result == "started"


# ==========================================
# תנועה בזמן (Movement Over Time)
# ==========================================

def test_valid_piece_move_updates_board_after_wait():
    board = Board.from_rows([
        ["wR", ".", "."],
        [".", ".", "."],
    ])
    controller, engine, _ = make_stack(board)

    controller.handle_click(50, 50)   # בחירת wR ב-(0,0)
    controller.handle_click(250, 50)  # תנועה ל-(0,2) - מרחק 2
    engine.wait(2000)

    assert controller.selected_pos is None
    assert board.to_rows()[0] == [".", ".", "wR"]


def test_knight_jumps_over_blockers():
    board = Board.from_rows([
        ["wN", "wP", "."],
        ["wP", "wP", "."],
        [".", ".", "."],
    ])
    controller, engine, _ = make_stack(board)

    controller.handle_click(50, 50)    # בחירת wN ב-(0,0)
    controller.handle_click(150, 250)  # תנועה בצורת L ל-(2,1)
    engine.wait(2000)

    assert controller.selected_pos is None
    assert board.get_cell(0, 0) == "."
    assert board.get_cell(2, 1) == "wN"


def test_capture_enemy_piece():
    board = Board.from_rows([
        ["wR", ".", "bR"],
        [".", ".", "."],
    ])
    controller, engine, _ = make_stack(board)

    controller.handle_click(50, 50)
    controller.handle_click(250, 50)  # אכילת bR ב-(0,2)
    engine.wait(2000)

    assert controller.selected_pos is None
    assert board.get_cell(0, 0) == "."
    assert board.get_cell(0, 2) == "wR"


def test_piece_does_not_move_before_arrival_time():
    board = Board.from_rows([["wR", ".", "."], [".", ".", "."]])
    controller, engine, _ = make_stack(board)
    controller.handle_click(50, 50)
    controller.handle_click(250, 50)  # תנועה ל-(0,2) - מרחק 2000ms

    engine.wait(1000)  # חצי דרך - עדיין לא הגיע!

    assert board.get_cell(0, 0) == "wR"
    assert board.get_cell(0, 2) == "."


def test_piece_arrives_after_wait_time():
    board = Board.from_rows([["wR", ".", "."], [".", ".", "."]])
    controller, engine, _ = make_stack(board)
    controller.handle_click(50, 50)
    controller.handle_click(250, 50)

    engine.wait(2000)  # 2000ms - הגיע ליעד!

    assert board.get_cell(0, 0) == "."
    assert board.get_cell(0, 2) == "wR"


# ==========================================
# מניעת שינוי מסלול ותנועה מיידית ללא Cooldown
# ==========================================

def test_cannot_redirect_piece_while_moving():
    board = Board.from_rows([["wR", ".", ".", "."], [".", ".", ".", "."]])
    controller, engine, _ = make_stack(board)

    # מתחילים תנועה מ-(0,0) ל-(0,3) - זמן דרוש: 3000ms
    controller.handle_click(50, 50)
    controller.handle_click(350, 50)

    engine.wait(1000)  # הכלי באמצע הדרך

    # ניסיון לבחור שוב את המשבצת המקורית ולתת פקודת תנועה ל-(0,1)
    controller.handle_click(50, 50)
    controller.handle_click(150, 50)

    engine.wait(2000)  # יתרת הזמן המקורית

    # הכלי היה אמור להגיע ליעד המקורי (0,3) ולא להיעצר ב-(0,1)
    assert board.to_rows()[0] == [".", ".", ".", "wR"]


def test_immediate_move_after_arrival_no_cooldown():
    board = Board.from_rows([["wR", ".", "."], [".", ".", "."]])
    controller, engine, _ = make_stack(board)

    # תנועה 1: מ-(0,0) ל-(0,2) -> דורש 2000ms
    controller.handle_click(50, 50)
    controller.handle_click(250, 50)
    engine.wait(2000)

    assert board.to_rows()[0] == [".", ".", "wR"]

    # תנועה 2 מיידית (ללא השהייה): מ-(0,2) חזרה ל-(0,0) -> דורש 2000ms
    controller.handle_click(250, 50)
    controller.handle_click(50, 50)
    engine.wait(2000)

    assert board.to_rows()[0] == ["wR", ".", "."]


# ==========================================
# אינטראקציות מתקדמות בזמן אמת
# ==========================================

def test_friendly_piece_landing_conflict():
    board = Board.from_rows([["wR", ".", "wB"], [".", ".", "."]])
    controller, engine, _ = make_stack(board)

    # 1. wR מתחיל לנוע מ-(0,0) ל-(0,1) -> יגיע עוד 1000ms
    controller.handle_click(50, 50)
    controller.handle_click(150, 50)

    # 2. wB ב-(0,2) מנסה לנוע ל-(0,1) [איפה ש-wR אמור לנחות]
    controller.handle_click(250, 50)
    controller.handle_click(150, 50)

    engine.wait(1000)

    # wR אמור להגיע ל-(0,1), ואילו wB אמור להישאר ב-(0,2) כי התנועה שלו נדחתה
    assert board.to_rows()[0] == [".", "wR", "wB"]


def test_invalid_premove_handling():
    board = Board.from_rows([["wR", "bR", "."], [".", ".", "."]])
    controller, engine, _ = make_stack(board)

    # bR נע מ-(0,1) ל-(0,2)
    controller.handle_click(150, 50)
    controller.handle_click(250, 50)

    # בזמן התנועה, wR מנסה לדלג מעל bR (מהלך לא חוקי)
    controller.handle_click(50, 50)
    controller.handle_click(250, 50)

    engine.wait(1000)

    # wR נשאר ב-(0,0), bR הגיע ל-(0,2)
    assert board.to_rows()[0] == ["wR", ".", "bR"]


# ==========================================
# סיום משחק בלכידת מלך (Game Over & King Capture)
# ==========================================

def test_game_over_on_king_capture():
    board = Board.from_rows([["wR", ".", "bK"], [".", ".", "."]])
    controller, engine, _ = make_stack(board)

    controller.handle_click(50, 50)
    controller.handle_click(250, 50)
    engine.wait(2000)

    assert board.to_rows()[0] == [".", ".", "wR"]
    assert engine.is_game_over() is True


def test_no_commands_processed_after_game_over():
    board = Board.from_rows([["wR", "bK", "bR"], [".", ".", "."]])
    controller, engine, _ = make_stack(board)

    # 1. wR אוכל את bK ב-(0,1)
    controller.handle_click(50, 50)
    controller.handle_click(150, 50)
    engine.wait(1000)

    assert engine.is_game_over() is True
    assert board.to_rows()[0] == [".", "wR", "bR"]

    # 2. ניסיון לבצע תנועה נוספת עם bR לאחר סיום המשחק
    controller.handle_click(250, 50)
    controller.handle_click(50, 50)
    engine.wait(2000)

    assert board.to_rows()[0] == [".", "wR", "bR"]


def test_ongoing_move_cancelled_if_king_captured_first():
    board = Board.from_rows([
        ["wR", ".", "bK"],
        [".", ".", "."],
        ["bR", ".", "."],
    ])
    controller, engine, _ = make_stack(board)

    # 1. bR ב-(2,0) נע ל-(2,2) -> מרחק 2, לוקח 2000ms
    controller.handle_click(50, 250)
    controller.handle_click(250, 250)

    # 2. wR ב-(0,0) נע ישירות לאכול את bK ב-(0,2) -> לוקח 2000ms
    controller.handle_click(50, 50)
    controller.handle_click(250, 50)

    engine.wait(2000)

    # ברגע ש-wR לוכד את bK, המשחק מסתיים מיד
    assert engine.is_game_over() is True
    assert board.to_rows()[0] == [".", ".", "wR"]


def test_pawn_promotion_to_queen():
    board = Board.from_rows([
        [".", "."],
        ["wP", "."],
        [".", "."],
        [".", "."],
    ])
    controller, engine, _ = make_stack(board)

    controller.handle_click(50, 150)
    controller.handle_click(50, 50)
    engine.wait(1000)

    assert board.get_cell(0, 0) == "wQ"
    assert board.get_cell(1, 0) == "."


# ==========================================
# הרחבת ה-jump (מחוץ ל-DSL הרשמי, ר' plan)
# ==========================================

def test_jump_airborne_captures_arriving_enemy():
    board = Board.from_rows([[".", ".", "."], ["wK", "bR", "."], [".", ".", "."]])
    controller, engine, _ = make_stack(board)

    controller.handle_jump(50, 150)   # wK קופץ (1,0)
    controller.handle_click(150, 150)  # בחירת bR (1,1)
    controller.handle_click(50, 150)   # יעד (1,0)
    engine.wait(1000)

    assert board.to_rows()[1] == ["wK", ".", "."]
    assert engine.is_game_over() is False


def test_jump_too_late_does_not_save_piece():
    board = Board.from_rows([[".", ".", "."], ["wK", "bR", "."], [".", ".", "."]])
    controller, engine, _ = make_stack(board)

    controller.handle_click(150, 150)
    controller.handle_click(50, 150)
    engine.wait(1000)

    controller.handle_jump(50, 150)  # מאוחר מדי - wK כבר נאכל

    assert board.to_rows()[1] == ["bR", ".", "."]
    assert engine.is_game_over() is True


def test_enemy_arrives_after_landing_captures_normally():
    board = Board.from_rows([[".", ".", ".", "."], ["wK", ".", ".", "bR"], [".", ".", ".", "."]])
    controller, engine, _ = make_stack(board)

    controller.handle_jump(50, 150)
    engine.wait(1000)  # הקפיצה הסתיימה

    controller.handle_click(350, 150)
    controller.handle_click(50, 150)
    engine.wait(3000)

    assert board.to_rows()[1] == ["bR", ".", ".", "."]
    assert engine.is_game_over() is True


def test_cannot_jump_while_moving():
    board = Board.from_rows([["wR", ".", "."]])
    controller, engine, arbiter = make_stack(board)

    controller.handle_click(50, 50)
    controller.handle_click(250, 50)

    controller.handle_jump(50, 50)
    assert len(arbiter.jumps) == 0


def test_cannot_jump_empty_cell():
    board = Board.from_rows([[".", ".", "."]])
    controller, engine, arbiter = make_stack(board)

    controller.handle_jump(50, 50)
    assert len(arbiter.jumps) == 0


def test_multiple_wait_increments_during_jump():
    board = Board.from_rows([[".", ".", "."], ["wK", "bR", "."], [".", ".", "."]])
    controller, engine, _ = make_stack(board)

    controller.handle_jump(50, 150)   # קפיצה ל-1000ms
    controller.handle_click(150, 150)
    controller.handle_click(50, 150)  # תנועה לוקחת 1000ms

    engine.wait(400)  # נשארו 600ms
    engine.wait(400)  # נשארו 200ms
    assert board.to_rows()[1] == ["wK", "bR", "."]  # bR עדיין בדרך

    engine.wait(400)  # 1200ms סה"כ -> bR הגיע בזמן שהיה באוויר ונלכד
    assert board.to_rows()[1] == ["wK", ".", "."]


def test_no_commands_after_game_over():
    board = Board.from_rows([["wK", "bR"]])
    controller, engine, arbiter = make_stack(board)

    # bR אוכל את wK
    controller.handle_click(150, 50)
    controller.handle_click(50, 50)
    engine.wait(1000)

    assert engine.is_game_over() is True

    controller.handle_jump(50, 50)
    controller.handle_click(50, 50)

    assert len(arbiter.jumps) == 0
    assert len(arbiter.motions) == 0

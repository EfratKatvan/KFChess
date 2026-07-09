from kungfu_chess.model.position import Position
from kungfu_chess.io.board_parser import build_board
from kungfu_chess.io.board_printer import format_board
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
    return board, controller, engine, arbiter


def row_tokens(board, row):
    return format_board(board)[row].split()


# ==========================================
# snapshot - תמונת מצב read-only ל-Renderer/BoardPrinter
# ==========================================

def test_snapshot_reflects_the_live_board_and_game_over():
    board, _, engine, _ = make_stack([["wR", "."]])
    snapshot = engine.snapshot()
    assert snapshot.board is board
    assert snapshot.game_over is False


def test_snapshot_reflects_game_over_after_king_capture():
    _, controller, engine, _ = make_stack([["wR", "bK"]])
    controller.handle_click(50, 50)
    controller.handle_click(150, 50)
    engine.wait(1000)

    assert engine.snapshot().game_over is True


# ==========================================
# שאילתות בסיסיות שה-Controller נשען עליהן (has_piece / is_same_color / can_select)
# ==========================================

def test_can_select_true_for_free_occupied_cell():
    _, _, engine, _ = make_stack([["wR", "."]])
    assert engine.can_select(Position(0, 0)) is True


def test_can_select_false_for_empty_cell():
    _, _, engine, _ = make_stack([["wR", "."]])
    assert engine.can_select(Position(0, 1)) is False


def test_can_select_false_for_busy_cell():
    _, controller, engine, _ = make_stack([["wR", ".", "."]])
    controller.handle_click(50, 50)
    controller.handle_click(250, 50)  # wR now mid-motion, selected_pos cleared
    assert engine.can_select(Position(0, 0)) is False


def test_can_select_false_once_game_is_over():
    _, controller, engine, _ = make_stack([["wR", "bK"]])
    controller.handle_click(50, 50)   # בחירת wR ב-(0,0)
    controller.handle_click(150, 50)  # wR אוכל את bK ב-(0,1)
    engine.wait(1000)
    assert engine.is_game_over() is True
    assert engine.can_select(Position(0, 1)) is False


def test_has_piece_true_for_occupied_cell():
    _, _, engine, _ = make_stack([["wR", "."]])
    assert engine.has_piece(Position(0, 0)) is True
    assert engine.has_piece(Position(0, 1)) is False


def test_is_same_color_true_for_two_friendly_pieces():
    _, _, engine, _ = make_stack([["wR", "wB"]])
    assert engine.is_same_color(Position(0, 0), Position(0, 1)) is True


def test_is_same_color_false_for_enemy_pieces():
    _, _, engine, _ = make_stack([["wR", "bB"]])
    assert engine.is_same_color(Position(0, 0), Position(0, 1)) is False


def test_is_same_color_false_when_either_cell_is_empty():
    _, _, engine, _ = make_stack([["wR", "."]])
    assert engine.is_same_color(Position(0, 0), Position(0, 1)) is False


def test_request_move_looks_up_the_piece_itself():
    _, _, engine, _ = make_stack([["wR", ".", "."]])
    result = engine.request_move(Position(0, 0), Position(0, 2))
    assert result.is_accepted is True
    assert result.reason == "ok"


def test_request_move_checks_game_over_before_asking_rule_engine():
    _, controller, engine, _ = make_stack([["wR", "bK"]])
    controller.handle_click(50, 50)   # בחירת wR
    controller.handle_click(150, 50)  # wR אוכל את bK
    engine.wait(1000)
    assert engine.is_game_over() is True

    result = engine.request_move(Position(0, 1), Position(0, 0))
    assert result.is_accepted is False
    assert result.reason == "game_over"


def test_request_move_reports_the_rule_engine_reason_when_invalid():
    _, _, engine, _ = make_stack([["wR", ".", "."], [".", ".", "."]])
    result = engine.request_move(Position(0, 0), Position(1, 1))
    assert result.is_accepted is False
    assert result.reason == "illegal_piece_move"


def test_request_move_rejects_a_piece_that_is_already_mid_motion():
    _, _, engine, _ = make_stack([["wR", ".", ".", "."]])
    first = engine.request_move(Position(0, 0), Position(0, 3))
    assert first.is_accepted is True

    second = engine.request_move(Position(0, 0), Position(0, 1))
    assert second.is_accepted is False
    assert second.reason == "motion_in_progress"


def test_request_move_allows_a_different_piece_to_move_while_another_is_in_flight():
    _, _, engine, _ = make_stack([["wR", ".", "."], [".", "bR", "."]])
    first = engine.request_move(Position(0, 0), Position(0, 2))
    assert first.is_accepted is True

    second = engine.request_move(Position(1, 1), Position(1, 0))
    assert second.is_accepted is True


# ==========================================
# תנועה בזמן (Movement Over Time)
# ==========================================

def test_valid_piece_move_updates_board_after_wait():
    board, controller, engine, _ = make_stack([
        ["wR", ".", "."],
        [".", ".", "."],
    ])

    controller.handle_click(50, 50)   # בחירת wR ב-(0,0)
    controller.handle_click(250, 50)  # תנועה ל-(0,2) - מרחק 2
    engine.wait(2000)

    assert controller.selected_pos is None
    assert row_tokens(board, 0) == [".", ".", "wR"]


def test_knight_jumps_over_blockers():
    board, controller, engine, _ = make_stack([
        ["wN", "wP", "."],
        ["wP", "wP", "."],
        [".", ".", "."],
    ])

    controller.handle_click(50, 50)    # בחירת wN ב-(0,0)
    controller.handle_click(150, 250)  # תנועה בצורת L ל-(2,1)
    engine.wait(2000)

    assert controller.selected_pos is None
    assert board.piece_at(Position(0, 0)) is None
    assert board.piece_at(Position(2, 1)) is not None


def test_capture_enemy_piece():
    board, controller, engine, _ = make_stack([
        ["wR", ".", "bR"],
        [".", ".", "."],
    ])

    controller.handle_click(50, 50)
    controller.handle_click(250, 50)  # אכילת bR ב-(0,2)
    engine.wait(2000)

    assert controller.selected_pos is None
    assert row_tokens(board, 0) == [".", ".", "wR"]


def test_piece_does_not_move_before_arrival_time():
    board, controller, engine, _ = make_stack([["wR", ".", "."], [".", ".", "."]])
    controller.handle_click(50, 50)
    controller.handle_click(250, 50)  # תנועה ל-(0,2) - מרחק 2000ms

    engine.wait(1000)  # חצי דרך - עדיין לא הגיע!

    assert row_tokens(board, 0) == ["wR", ".", "."]


def test_piece_arrives_after_wait_time():
    board, controller, engine, _ = make_stack([["wR", ".", "."], [".", ".", "."]])
    controller.handle_click(50, 50)
    controller.handle_click(250, 50)

    engine.wait(2000)  # 2000ms - הגיע ליעד!

    assert row_tokens(board, 0) == [".", ".", "wR"]


# ==========================================
# מניעת שינוי מסלול ותנועה מיידית ללא Cooldown
# ==========================================

def test_cannot_redirect_piece_while_moving():
    board, controller, engine, _ = make_stack([["wR", ".", ".", "."], [".", ".", ".", "."]])

    # מתחילים תנועה מ-(0,0) ל-(0,3) - זמן דרוש: 3000ms
    controller.handle_click(50, 50)
    controller.handle_click(350, 50)

    engine.wait(1000)  # הכלי באמצע הדרך

    # ניסיון לבחור שוב את המשבצת המקורית ולתת פקודת תנועה ל-(0,1)
    controller.handle_click(50, 50)
    controller.handle_click(150, 50)

    engine.wait(2000)  # יתרת הזמן המקורית

    # הכלי היה אמור להגיע ליעד המקורי (0,3) ולא להיעצר ב-(0,1)
    assert row_tokens(board, 0) == [".", ".", ".", "wR"]


def test_immediate_move_after_arrival_no_cooldown():
    board, controller, engine, _ = make_stack([["wR", ".", "."], [".", ".", "."]])

    # תנועה 1: מ-(0,0) ל-(0,2) -> דורש 2000ms
    controller.handle_click(50, 50)
    controller.handle_click(250, 50)
    engine.wait(2000)

    assert row_tokens(board, 0) == [".", ".", "wR"]

    # תנועה 2 מיידית (ללא השהייה): מ-(0,2) חזרה ל-(0,0) -> דורש 2000ms
    controller.handle_click(250, 50)
    controller.handle_click(50, 50)
    engine.wait(2000)

    assert row_tokens(board, 0) == ["wR", ".", "."]


# ==========================================
# אינטראקציות מתקדמות בזמן אמת
# ==========================================

def test_friendly_piece_landing_conflict():
    board, controller, engine, _ = make_stack([["wR", ".", "wB"], [".", ".", "."]])

    # 1. wR מתחיל לנוע מ-(0,0) ל-(0,1) -> יגיע עוד 1000ms
    controller.handle_click(50, 50)
    controller.handle_click(150, 50)

    # 2. wB ב-(0,2) מנסה לנוע ל-(0,1) [איפה ש-wR אמור לנחות]
    controller.handle_click(250, 50)
    controller.handle_click(150, 50)

    engine.wait(1000)

    # wR אמור להגיע ל-(0,1), ואילו wB אמור להישאר ב-(0,2) כי התנועה שלו נדחתה
    assert row_tokens(board, 0) == [".", "wR", "wB"]


def test_invalid_premove_handling():
    board, controller, engine, _ = make_stack([["wR", "bR", "."], [".", ".", "."]])

    # bR נע מ-(0,1) ל-(0,2)
    controller.handle_click(150, 50)
    controller.handle_click(250, 50)

    # בזמן התנועה, wR מנסה לדלג מעל bR (מהלך לא חוקי)
    controller.handle_click(50, 50)
    controller.handle_click(250, 50)

    engine.wait(1000)

    # wR נשאר ב-(0,0), bR הגיע ל-(0,2)
    assert row_tokens(board, 0) == ["wR", ".", "bR"]


# ==========================================
# סיום משחק בלכידת מלך (Game Over & King Capture)
# ==========================================

def test_game_over_on_king_capture():
    board, controller, engine, _ = make_stack([["wR", ".", "bK"], [".", ".", "."]])

    controller.handle_click(50, 50)
    controller.handle_click(250, 50)
    engine.wait(2000)

    assert row_tokens(board, 0) == [".", ".", "wR"]
    assert engine.is_game_over() is True


def test_no_commands_processed_after_game_over():
    board, controller, engine, _ = make_stack([["wR", "bK", "bR"], [".", ".", "."]])

    # 1. wR אוכל את bK ב-(0,1)
    controller.handle_click(50, 50)
    controller.handle_click(150, 50)
    engine.wait(1000)

    assert engine.is_game_over() is True
    assert row_tokens(board, 0) == [".", "wR", "bR"]

    # 2. ניסיון לבצע תנועה נוספת עם bR לאחר סיום המשחק
    controller.handle_click(250, 50)
    controller.handle_click(50, 50)
    engine.wait(2000)

    assert row_tokens(board, 0) == [".", "wR", "bR"]


def test_ongoing_move_cancelled_if_king_captured_first():
    board, controller, engine, _ = make_stack([
        ["wR", ".", "bK"],
        [".", ".", "."],
        ["bR", ".", "."],
    ])

    # 1. bR ב-(2,0) נע ל-(2,2) -> מרחק 2, לוקח 2000ms
    controller.handle_click(50, 250)
    controller.handle_click(250, 250)

    # 2. wR ב-(0,0) נע ישירות לאכול את bK ב-(0,2) -> לוקח 2000ms
    controller.handle_click(50, 50)
    controller.handle_click(250, 50)

    engine.wait(2000)

    # ברגע ש-wR לוכד את bK, המשחק מסתיים מיד
    assert engine.is_game_over() is True
    assert row_tokens(board, 0) == [".", ".", "wR"]


def test_pawn_promotion_to_queen():
    board, controller, engine, _ = make_stack([
        [".", "."],
        ["wP", "."],
        [".", "."],
        [".", "."],
    ])

    controller.handle_click(50, 150)
    controller.handle_click(50, 50)
    engine.wait(1000)

    assert row_tokens(board, 0) == ["wQ", "."]
    assert board.piece_at(Position(1, 0)) is None


# ==========================================
# הרחבת ה-jump (מחוץ ל-DSL הרשמי, ר' plan)
# ==========================================

def test_jump_airborne_captures_arriving_enemy():
    board, controller, engine, _ = make_stack([[".", ".", "."], ["wK", "bR", "."], [".", ".", "."]])

    controller.handle_jump(50, 150)    # wK קופץ (1,0)
    controller.handle_click(150, 150)  # בחירת bR (1,1)
    controller.handle_click(50, 150)   # יעד (1,0)
    engine.wait(1000)

    assert row_tokens(board, 1) == ["wK", ".", "."]
    assert engine.is_game_over() is False


def test_jump_too_late_does_not_save_piece():
    board, controller, engine, _ = make_stack([[".", ".", "."], ["wK", "bR", "."], [".", ".", "."]])

    controller.handle_click(150, 150)
    controller.handle_click(50, 150)
    engine.wait(1000)

    controller.handle_jump(50, 150)  # מאוחר מדי - wK כבר נאכל

    assert row_tokens(board, 1) == ["bR", ".", "."]
    assert engine.is_game_over() is True


def test_enemy_arrives_after_landing_captures_normally():
    board, controller, engine, _ = make_stack(
        [[".", ".", ".", "."], ["wK", ".", ".", "bR"], [".", ".", ".", "."]]
    )

    controller.handle_jump(50, 150)
    engine.wait(1000)  # הקפיצה הסתיימה

    controller.handle_click(350, 150)
    controller.handle_click(50, 150)
    engine.wait(3000)

    assert row_tokens(board, 1) == ["bR", ".", ".", "."]
    assert engine.is_game_over() is True


def test_cannot_jump_while_moving():
    _, controller, engine, arbiter = make_stack([["wR", ".", "."]])

    controller.handle_click(50, 50)
    controller.handle_click(250, 50)

    controller.handle_jump(50, 50)
    assert len(arbiter.jumps) == 0


def test_cannot_jump_empty_cell():
    _, controller, engine, arbiter = make_stack([[".", ".", "."]])

    controller.handle_jump(50, 50)
    assert len(arbiter.jumps) == 0


def test_multiple_wait_increments_during_jump():
    board, controller, engine, _ = make_stack([[".", ".", "."], ["wK", "bR", "."], [".", ".", "."]])

    controller.handle_jump(50, 150)   # קפיצה ל-1000ms
    controller.handle_click(150, 150)
    controller.handle_click(50, 150)  # תנועה לוקחת 1000ms

    engine.wait(400)  # נשארו 600ms
    engine.wait(400)  # נשארו 200ms
    assert row_tokens(board, 1) == ["wK", "bR", "."]  # bR עדיין בדרך

    engine.wait(400)  # 1200ms סה"כ -> bR הגיע בזמן שהיה באוויר ונלכד
    assert row_tokens(board, 1) == ["wK", ".", "."]


def test_no_commands_after_game_over():
    _, controller, engine, arbiter = make_stack([["wK", "bR"]])

    # bR אוכל את wK
    controller.handle_click(150, 50)
    controller.handle_click(50, 50)
    engine.wait(1000)

    assert engine.is_game_over() is True

    controller.handle_jump(50, 50)
    controller.handle_click(50, 50)

    assert len(arbiter.jumps) == 0
    assert len(arbiter.motions) == 0

import pytest
from board.model import Board
from game.controller import GameController, is_legal_piece_move


# ==========================================
# איטרציה 3: חוקי תנועה בסיסיים לכל הכלים (is_legal_piece_move)
# ==========================================

def test_king_movement_rules():
    assert is_legal_piece_move("wK", (1, 1), (1, 2)) is True
    assert is_legal_piece_move("wK", (1, 1), (2, 2)) is True
    assert is_legal_piece_move("wK", (1, 1), (1, 3)) is False


def test_rook_movement_rules():
    assert is_legal_piece_move("wR", (0, 0), (0, 3)) is True
    assert is_legal_piece_move("wR", (0, 0), (3, 0)) is True
    assert is_legal_piece_move("wR", (0, 0), (2, 2)) is False


def test_bishop_movement_rules():
    assert is_legal_piece_move("wB", (0, 0), (3, 3)) is True
    assert is_legal_piece_move("wB", (0, 0), (0, 2)) is False


def test_queen_movement_rules():
    assert is_legal_piece_move("wQ", (0, 0), (0, 2)) is True
    assert is_legal_piece_move("wQ", (0, 0), (2, 2)) is True
    assert is_legal_piece_move("wQ", (0, 0), (1, 2)) is False


def test_knight_movement_rules():
    assert is_legal_piece_move("wN", (0, 0), (2, 1)) is True
    assert is_legal_piece_move("wN", (0, 0), (1, 2)) is True
    assert is_legal_piece_move("wN", (0, 0), (2, 2)) is False


# ==========================================
# איטרציה 3: לחיצות, בחירת כלים ושינוי בחירה
# ==========================================

def test_click_outside_board():
    board = Board.from_rows([["wR", "."]])
    controller = GameController(board)
    controller.execute_command("click -10 50")
    assert controller.selected_pos is None


def test_click_empty_cell_no_selection():
    board = Board.from_rows([["."]])
    controller = GameController(board)
    controller.execute_command("click 50 50")
    assert controller.selected_pos is None


def test_select_piece():
    board = Board.from_rows([["wR"]])
    controller = GameController(board)
    controller.execute_command("click 50 50")
    assert controller.selected_pos == (0, 0)


def test_change_selection_to_another_piece():
    board = Board.from_rows([["wR", "wB"]])
    controller = GameController(board)
    controller.execute_command("click 50 50")   # בחירת wR
    controller.execute_command("click 150 50")  # שינוי בחירה ל-wB
    assert controller.selected_pos == (0, 1)


def test_click_same_selected_piece_keeps_selection():
    board = Board.from_rows([["wR"]])
    controller = GameController(board)
    controller.execute_command("click 50 50")
    controller.execute_command("click 50 50")
    assert controller.selected_pos == (0, 0)


# ==========================================
# איטרציה 3: עדכון הלוח ותנועות לא חוקיות (עם wait שנדרש מאיטרציה 6)
# ==========================================

def test_controller_valid_piece_move_updates_board():
    board = Board.from_rows([
        ["wR", ".", "."],
        [".", ".", "."]
    ])
    controller = GameController(board)

    controller.execute_command("click 50 50")   # בחירת wR ב-(0,0)
    controller.execute_command("click 250 50")  # תנועה ל-(0,2) - מרחק 2
    controller.execute_command("wait 2000")      # תוספת wait לאיטרציה 6

    assert controller.selected_pos is None
    assert board._rows[0] == [".", ".", "wR"]


def test_controller_invalid_piece_move_ignored():
    board = Board.from_rows([
        ["wR", ".", "."],
        [".", ".", "."]
    ])
    controller = GameController(board)

    controller.execute_command("click 50 50")   # בחירת wR ב-(0,0)
    controller.execute_command("click 150 150") # תנועה לא חוקית באלכסון

    assert board._rows[0] == ["wR", ".", "."]


# ==========================================
# איטרציה 4: חסימות, דילוג של פרש ואכילת כלי אויב (עם wait)
# ==========================================

def test_rook_blocked_by_piece():
    board = Board.from_rows([
        ["wR", "wP", "."],
        [".", ".", "."]
    ])
    controller = GameController(board)

    controller.execute_command("click 50 50")   # בחירת wR ב-(0,0)
    controller.execute_command("click 250 50")  # ניסיון לא חוקי לדלג מעל wP

    # ניסיון התנועה נכשל, הבחירה נשארת על הצריח ב-(0,0) והלוח לא משתנה
    assert controller.selected_pos == (0, 0)
    assert board._rows[0] == ["wR", "wP", "."]


def test_knight_jumps_over_blockers():
    board = Board.from_rows([
        ["wN", "wP", "."],
        ["wP", "wP", "."],
        [".", ".", "."]
    ])
    controller = GameController(board)

    controller.execute_command("click 50 50")   # בחירת wN ב-(0,0)
    controller.execute_command("click 150 250") # תנועה בצורת L ל-(2,1)
    controller.execute_command("wait 2000")      # תוספת wait לאיטרציה 6

    assert controller.selected_pos is None
    assert board._rows[0][0] == "."
    assert board._rows[2][1] == "wN"


def test_capture_enemy_piece():
    board = Board.from_rows([
        ["wR", ".", "bR"],
        [".", ".", "."]
    ])
    controller = GameController(board)

    controller.execute_command("click 50 50")   # בחירת wR ב-(0,0)
    controller.execute_command("click 250 50")  # אכילת bR ב-(0,2)
    controller.execute_command("wait 2000")      # תוספת wait לאיטרציה 6

    assert controller.selected_pos is None
    assert board._rows[0][0] == "."
    assert board._rows[0][2] == "wR"


def test_cannot_capture_own_piece():
    board = Board.from_rows([
        ["wR", ".", "wB"],
        [".", ".", "."]
    ])
    controller = GameController(board)

    controller.execute_command("click 50 50")   # בחירת wR ב-(0,0)
    controller.execute_command("click 250 50")  # ניסיון אכילה של כלי ידידותי

    assert controller.selected_pos == (0, 2)
    assert board._rows[0] == ["wR", ".", "wB"]


# ==========================================
# איטרציה 6: תנועה בזמן (Movement Over Time)
# ==========================================

def test_piece_does_not_move_before_arrival_time():
    """הכלי אינו עובר למשבצת היעד לפני שחלף זמן ההגעה."""
    board = Board.from_rows([
        ["wR", ".", "."],
        [".", ".", "."]
    ])
    controller = GameController(board)
    controller.execute_command("click 50 50")   # בחירת wR ב-(0,0)
    controller.execute_command("click 250 50")  # תנועה ל-(0,2) - מרחק 2000ms

    controller.execute_command("wait 1000")     # חצי דרך - עדיין לא הגיע!

    assert board._rows[0][0] == "wR"
    assert board._rows[0][2] == "."


def test_piece_arrives_after_wait_time():
    """הכלי מגיע למשבצת היעד לאחר שעבר זמן ההגעה המלא."""
    board = Board.from_rows([
        ["wR", ".", "."],
        [".", ".", "."]
    ])
    controller = GameController(board)
    controller.execute_command("click 50 50")   # בחירת wR ב-(0,0)
    controller.execute_command("click 250 50")  # תנועה ל-(0,2)

    controller.execute_command("wait 2000")     # 2000ms - הגיע ליעד!

    assert board._rows[0][0] == "."
    assert board._rows[0][2] == "wR"

# ==========================================
# איטרציה 7: מניעת שינוי מסלול ותנועה מיידית ללא Cooldown
# ==========================================

def test_cannot_redirect_piece_while_moving():
    """בדיקה שלא ניתן להסיט כלי ממסלולו או לבחור אותו מחדש תוך כדי תנועה."""
    board = Board.from_rows([
        ["wR", ".", ".", "."],
        [".", ".", ".", "."]
    ])
    controller = GameController(board)

    # מתחילים תנועה מ-(0,0) ל-(0,3) - זמן דרוש: 3000ms
    controller.execute_command("click 50 50")
    controller.execute_command("click 350 50")

    # מחכים 1000ms - הכלי באמצע הדרך
    controller.execute_command("wait 1000")

    # ניסיון לבחור שוב את המשבצת המקורית ולתת פקודת תנועה ל-(0,1)
    controller.execute_command("click 50 50")
    controller.execute_command("click 150 50")

    # מציגים המתנה ליתרת הזמן המקורית (עוד 2000ms)
    controller.execute_command("wait 2000")

    # הכלי היה אמור להגיע ליעד המקורי (0,3) ולא להיעצר ב-(0,1)
    assert board._rows[0] == [".", ".", ".", "wR"]


def test_immediate_move_after_arrival_no_cooldown():
    """בדיקה שמיד ברגע שהכלי מגיע ליעדו ניתן לבחור ולהניע אותו שוב ללא השהייה."""
    board = Board.from_rows([
        ["wR", ".", "."],
        [".", ".", "."]
    ])
    controller = GameController(board)

    # תנועה 1: מ-(0,0) ל-(0,2) -> דורש 2000ms
    controller.execute_command("click 50 50")
    controller.execute_command("click 250 50")
    controller.execute_command("wait 2000")

    assert board._rows[0] == [".", ".", "wR"]

    # תנועה 2 מיידית (ללא השהייה): מ-(0,2) חזרה ל-(0,0) -> דורש 2000ms
    controller.execute_command("click 250 50")
    controller.execute_command("click 50 50")
    controller.execute_command("wait 2000")

    assert board._rows[0] == ["wR", ".", "."]

# ==========================================
# איטרציה 8: אינטראקציות מתקדמות בזמן אמת
# ==========================================

def test_friendly_piece_landing_conflict():
    """בדיקה שלא ניתן להורות לכלי לנוע לתא שבו מתוכנן לנחות כלי ידידותי."""
    board = Board.from_rows([
        ["wR", ".", "wB"],
        [".", ".", "."]
    ])
    controller = GameController(board)

    # 1. wR מתחיל לנוע מ-(0,0) ל-(0,1) -> יגיע עוד 1000ms
    controller.execute_command("click 50 50")
    controller.execute_command("click 150 50")

    # 2. wB ב-(0,2) מנסה לנוע ל-(0,1) [איפה ש-wR אמור לנחות]
    controller.execute_command("click 250 50")
    controller.execute_command("click 150 50")

    # מריצים את הזמן עד סיום התנועה
    controller.execute_command("wait 1000")

    # wR אמור להגיע ל-(0,1), ואילו wB אמור להישאר ב-(0,2) כי התנועה שלו נדחתה
    assert board._rows[0] == [".", "wR", "wB"]


def test_invalid_premove_handling():
    """בדיקה שפקודה לא חוקית שניתנת בזמן שכלים נעים נדחית כראוי."""
    board = Board.from_rows([
        ["wR", "bR", "."],
        [".", ".", "."]
    ])
    controller = GameController(board)

    # bR נע מ-(0,1) ל-(0,2)
    controller.execute_command("click 150 50")
    controller.execute_command("click 250 50")

    # בזמן התנועה, wR מנסה לדלג מעל bR (מהלך לא חוקי)
    controller.execute_command("click 50 50")
    controller.execute_command("click 250 50")

    controller.execute_command("wait 1000")

    # wR נשאר ב-(0,0), bR הגיע ל-(0,2)
    assert board._rows[0] == ["wR", ".", "bR"]

# ==========================================
# איטרציה 9: סיום משחק בלכידת מלך (Game Over & King Capture)
# ==========================================

def test_game_over_on_king_capture():
    """בדיקה שבביצוע אכילה של מלך, המשחק מסתיים והדגל game_over מופעל."""
    board = Board.from_rows([
        ["wR", ".", "bK"],
        [".", ".", "."]
    ])
    controller = GameController(board)

    # wR נע מ-(0,0) ל-(0,2) שבו נמצא bK
    controller.execute_command("click 50 50")
    controller.execute_command("click 250 50")
    controller.execute_command("wait 2000")

    # המלך שחור נאכל, wR עומד בתא (0,2) והמשחק מסתיים
    assert board._rows[0] == [".", ".", "wR"]
    assert controller.game_over is True


def test_no_commands_processed_after_game_over():
    """בדיקה ולאחר שהמשחק הסתיים, פקודות click נוספות נדחות לחלוטין."""
    board = Board.from_rows([
        ["wR", "bK", "bR"],
        [".", ".", "."]
    ])
    controller = GameController(board)

    # 1. wR אוכל את bK ב-(0,1)
    controller.execute_command("click 50 50")
    controller.execute_command("click 150 50")
    controller.execute_command("wait 1000")

    assert controller.game_over is True
    assert board._rows[0] == [".", "wR", "bR"]

    # 2. ניסיון לבצע תנועה נוספת עם bR לאחר סיום המשחק
    controller.execute_command("click 250 50")
    controller.execute_command("click 50 50")
    controller.execute_command("wait 2000")

    # bR לא אמור לנוע כי המשחק כבר הסתיים
    assert board._rows[0] == [".", "wR", "bR"]


def test_ongoing_move_cancelled_if_king_captured_first():
    """בדיקה שאם מלך נלכד, תנועות פעילות אחרות שטרם הסתיימו מבוטלות ולא מתממשות."""
    board = Board.from_rows([
        ["wR", ".", "bK"],
        [".", ".", "."],
        ["bR", ".", "."]
    ])
    controller = GameController(board)

    # 1. bR ב-(2,0) נע ל-(2,2) -> מרחק 2, לוקח 2000ms
    controller.execute_command("click 50 250")   # בחירת bR ב-(2,0)
    controller.execute_command("click 250 250")  # יעד (2,2)

    # 2. wR ב-(0,0) נע אנכית/אופקית ישירות לאכול את bK ב-(0,2) -> לוקח 2000ms
    controller.execute_command("click 50 50")    # בחירת wR ב-(0,0)
    controller.execute_command("click 250 50")   # יעד bK ב-(0,2)

    # מריצים את ה-wait לזמן סיום התנועה
    controller.execute_command("wait 2000")

    # ברגע ש-wR לוכד את bK, המשחק מסתיים מיד וכל התנועות הנוספות מוצררות/מופסקות
    assert controller.game_over is True
    assert board._rows[0] == [".", ".", "wR"]

# ==========================================
# איטרציה 10: חוקי תנועה והכתרה של חייל (Pawn Rules)
# ==========================================

def test_pawn_single_step_forward():
    board = [
        [".", "."],
        [".", "."],
        [".", "."],
        ["wP", "."]  # לבן בשורה 3 (תחתית)
    ]
    # צעד בודד למעלה משורה 3 לשורה 2
    assert is_legal_piece_move("wP", (3, 0), (2, 0), board, ".") is True


def test_pawn_double_step_from_start_row():
    board = [
        [".", "."],
        [".", "."],
        [".", "."],
        ["wP", "."]  # שורת ההתחלה של לבן בלוח קטן היא 3
    ]
    # צעד כפול משורת ההתחלה (שורה 3 -> שורה 1)
    assert is_legal_piece_move("wP", (3, 0), (1, 0), board, ".") is True


def test_pawn_double_step_blocked():
    board = [
        [".", "."],
        [".", "."],
        ["bP", "."],  # חסום בשורה 2
        ["wP", "."]
    ]
    assert is_legal_piece_move("wP", (3, 0), (1, 0), board, ".") is False

def test_pawn_diagonal_capture():
    board = [
        [".", "."],
        [".", "bP"], # אויב באלכסון בשורה 1
        ["wP", "."],
        [".", "."]
    ]
    # אכילת אויב באלכסון למעלה (2,0) -> (1,1)
    assert is_legal_piece_move("wP", (2, 0), (1, 1), board, "bP") is True
    # תנועה באלכסון לתא ריק - לא חוקית
    assert is_legal_piece_move("wP", (2, 0), (1, 1), board, ".") is False


def test_pawn_promotion_to_queen():
    board = Board.from_rows([
        [".", "."],
        ["wP", "."],  # wP בשורה 1 (צעד אחד משורה 0)
        [".", "."],
        [".", "."]
    ])
    controller = GameController(board)

    # wP ב-(1,0) נע למעלה ל-(0,0) (השורה הראשונה/עליונה)
    controller.execute_command("click 50 150")
    controller.execute_command("click 50 50")
    controller.execute_command("wait 1000")

    # החייל הופך למלכה wQ בסיום התנועה בשורה 0
    assert board._rows[0][0] == "wQ"
    assert board._rows[1][0] == "."
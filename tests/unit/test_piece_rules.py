from kungfu_chess.rules.piece_rules import is_legal_piece_move


# ==========================================
# חוקי תנועה בסיסיים לכל הכלים
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
# חוקי תנועה והכתרה של חייל (Pawn Rules)
# ==========================================

def test_pawn_single_step_forward():
    board = [
        [".", "."],
        [".", "."],
        [".", "."],
        ["wP", "."],  # לבן בשורה 3 (תחתית)
    ]
    # צעד בודד למעלה משורה 3 לשורה 2
    assert is_legal_piece_move("wP", (3, 0), (2, 0), board, ".") is True


def test_pawn_double_step_from_start_row():
    board = [
        [".", "."],
        [".", "."],
        [".", "."],
        ["wP", "."],  # שורת ההתחלה של לבן בלוח קטן היא 3
    ]
    # צעד כפול משורת ההתחלה (שורה 3 -> שורה 1)
    assert is_legal_piece_move("wP", (3, 0), (1, 0), board, ".") is True


def test_pawn_double_step_blocked():
    board = [
        [".", "."],
        [".", "."],
        ["bP", "."],  # חסום בשורה 2
        ["wP", "."],
    ]
    assert is_legal_piece_move("wP", (3, 0), (1, 0), board, ".") is False


def test_pawn_diagonal_capture():
    board = [
        [".", "."],
        [".", "bP"],  # אויב באלכסון בשורה 1
        ["wP", "."],
        [".", "."],
    ]
    # אכילת אויב באלכסון למעלה (2,0) -> (1,1)
    assert is_legal_piece_move("wP", (2, 0), (1, 1), board, "bP") is True
    # תנועה באלכסון לתא ריק - לא חוקית
    assert is_legal_piece_move("wP", (2, 0), (1, 1), board, ".") is False

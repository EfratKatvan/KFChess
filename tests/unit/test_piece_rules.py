from kungfu_chess.model.board import Board
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, WHITE, BLACK, KING, QUEEN, ROOK, BISHOP, KNIGHT, PAWN
from kungfu_chess.rules.piece_rules import is_legal_piece_move


def piece(kind, color=WHITE, row=0, col=0):
    return Piece(id=f"{color}-{kind}", color=color, kind=kind, cell=Position(row, col))


# ==========================================
# חוקי תנועה בסיסיים לכל הכלים (ללא לוח - גיאומטריה טהורה)
# ==========================================

def test_king_movement_rules():
    king = piece(KING)
    assert is_legal_piece_move(king, Position(1, 1), Position(1, 2)) is True
    assert is_legal_piece_move(king, Position(1, 1), Position(2, 2)) is True
    assert is_legal_piece_move(king, Position(1, 1), Position(1, 3)) is False


def test_rook_movement_rules():
    rook = piece(ROOK)
    assert is_legal_piece_move(rook, Position(0, 0), Position(0, 3)) is True
    assert is_legal_piece_move(rook, Position(0, 0), Position(3, 0)) is True
    assert is_legal_piece_move(rook, Position(0, 0), Position(2, 2)) is False


def test_bishop_movement_rules():
    bishop = piece(BISHOP)
    assert is_legal_piece_move(bishop, Position(0, 0), Position(3, 3)) is True
    assert is_legal_piece_move(bishop, Position(0, 0), Position(0, 2)) is False


def test_queen_movement_rules():
    queen = piece(QUEEN)
    assert is_legal_piece_move(queen, Position(0, 0), Position(0, 2)) is True
    assert is_legal_piece_move(queen, Position(0, 0), Position(2, 2)) is True
    assert is_legal_piece_move(queen, Position(0, 0), Position(1, 2)) is False


def test_knight_movement_rules():
    knight = piece(KNIGHT)
    assert is_legal_piece_move(knight, Position(0, 0), Position(2, 1)) is True
    assert is_legal_piece_move(knight, Position(0, 0), Position(1, 2)) is True
    assert is_legal_piece_move(knight, Position(0, 0), Position(2, 2)) is False


def test_moving_onto_own_color_piece_is_rejected():
    rook = piece(ROOK, color=WHITE, row=0, col=0)
    board = Board(width=3, height=1)
    board.add_piece(rook)
    board.add_piece(piece(BISHOP, color=WHITE, row=0, col=2))
    assert is_legal_piece_move(rook, Position(0, 0), Position(0, 2), board) is False


def test_rook_blocked_by_piece_in_path():
    rook = piece(ROOK, color=WHITE, row=0, col=0)
    board = Board(width=3, height=1)
    board.add_piece(rook)
    board.add_piece(piece(PAWN, color=WHITE, row=0, col=1))
    assert is_legal_piece_move(rook, Position(0, 0), Position(0, 2), board) is False


# ==========================================
# חוקי תנועה והכתרה של חייל (Pawn Rules)
# ==========================================

def test_pawn_single_step_forward():
    board = Board(width=1, height=4)
    pawn = piece(PAWN, color=WHITE, row=3, col=0)
    board.add_piece(pawn)
    # צעד בודד למעלה משורה 3 לשורה 2
    assert is_legal_piece_move(pawn, Position(3, 0), Position(2, 0), board) is True


def test_pawn_double_step_from_start_row():
    board = Board(width=1, height=4)
    pawn = piece(PAWN, color=WHITE, row=3, col=0)
    board.add_piece(pawn)
    # צעד כפול משורת ההתחלה (שורה 3 -> שורה 1)
    assert is_legal_piece_move(pawn, Position(3, 0), Position(1, 0), board) is True


def test_pawn_double_step_blocked():
    board = Board(width=1, height=4)
    pawn = piece(PAWN, color=WHITE, row=3, col=0)
    board.add_piece(pawn)
    board.add_piece(piece(PAWN, color=BLACK, row=2, col=0))  # חוסם בשורה 2
    assert is_legal_piece_move(pawn, Position(3, 0), Position(1, 0), board) is False


def test_pawn_diagonal_capture():
    board = Board(width=2, height=4)
    pawn = piece(PAWN, color=WHITE, row=2, col=0)
    board.add_piece(pawn)
    board.add_piece(piece(PAWN, color=BLACK, row=1, col=1))  # אויב באלכסון

    # אכילת אויב באלכסון למעלה (2,0) -> (1,1)
    assert is_legal_piece_move(pawn, Position(2, 0), Position(1, 1), board) is True


def test_pawn_diagonal_move_to_empty_cell_is_illegal():
    board = Board(width=2, height=4)
    pawn = piece(PAWN, color=WHITE, row=2, col=0)
    board.add_piece(pawn)
    # תא (1,1) ריק - תנועה באלכסון לתא ריק לא חוקית
    assert is_legal_piece_move(pawn, Position(2, 0), Position(1, 1), board) is False

from kungfu_chess.model.board import Board
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, WHITE, BLACK, KING, QUEEN, ROOK, BISHOP, KNIGHT, PAWN
from kungfu_chess.rules.piece_rules import (
    RookRules,
    BishopRules,
    QueenRules,
    KnightRules,
    KingRules,
    PawnRules,
    rules_for,
)


def piece(kind, color=WHITE, row=0, col=0):
    return Piece(id=f"{color}-{kind}-{row}-{col}", color=color, kind=kind, cell=Position(row, col))


def board_with(*pieces, width=8, height=8):
    board = Board(width=width, height=height)
    for p in pieces:
        board.add_piece(p)
    return board


# ==========================================
# 1. Rook
# ==========================================

def test_rook_moves_across_empty_row_and_column():
    rook = piece(ROOK, row=0, col=0)
    board = board_with(rook)
    destinations = RookRules.legal_destinations(board, rook)
    assert Position(0, 7) in destinations  # לאורך השורה
    assert Position(7, 0) in destinations  # לאורך העמודה
    assert Position(1, 1) not in destinations  # לא אלכסון


def test_rook_stops_before_a_friendly_blocker():
    rook = piece(ROOK, WHITE, 0, 0)
    blocker = piece(ROOK, WHITE, 0, 3)
    board = board_with(rook, blocker)
    destinations = RookRules.legal_destinations(board, rook)
    assert Position(0, 2) in destinations
    assert Position(0, 3) not in destinations  # תא הכלי הידידותי עצמו
    assert Position(0, 4) not in destinations  # מעבר לו


def test_rook_captures_an_enemy_blocker_but_does_not_pass_it():
    rook = piece(ROOK, WHITE, 0, 0)
    enemy = piece(ROOK, BLACK, 0, 3)
    board = board_with(rook, enemy)
    destinations = RookRules.legal_destinations(board, rook)
    assert Position(0, 3) in destinations  # אכילה
    assert Position(0, 4) not in destinations  # לא ממשיך אחרי האכילה


# ==========================================
# 2. Bishop
# ==========================================

def test_bishop_moves_diagonally_and_not_straight():
    bishop = piece(BISHOP, row=0, col=0)
    board = board_with(bishop)
    destinations = BishopRules.legal_destinations(board, bishop)
    assert Position(3, 3) in destinations
    assert Position(0, 3) not in destinations  # ישר - לא חוקי לרץ


# ==========================================
# 3. Queen
# ==========================================

def test_queen_combines_rook_and_bishop_movement():
    queen = piece(QUEEN, row=0, col=0)
    board = board_with(queen)
    destinations = QueenRules.legal_destinations(board, queen)
    assert Position(0, 5) in destinations  # ישר כמו צריח
    assert Position(5, 5) in destinations  # אלכסון כמו רץ
    assert Position(1, 2) not in destinations  # לא ישר ולא אלכסון


# ==========================================
# 4. Knight
# ==========================================

def test_knight_jumps_over_blockers():
    knight = piece(KNIGHT, WHITE, 0, 0)
    board = board_with(
        knight,
        piece(PAWN, WHITE, 0, 1),
        piece(PAWN, WHITE, 1, 0),
        piece(PAWN, WHITE, 1, 1),
    )
    destinations = KnightRules.legal_destinations(board, knight)
    assert Position(2, 1) in destinations
    assert Position(1, 2) in destinations


# ==========================================
# 5. King
# ==========================================

def test_king_moves_one_cell_only():
    king = piece(KING, row=4, col=4)
    board = board_with(king)
    destinations = KingRules.legal_destinations(board, king)
    assert Position(4, 5) in destinations
    assert Position(3, 3) in destinations
    assert Position(4, 6) not in destinations
    assert len(destinations) == 8


# ==========================================
# 6. Pawn - תנועה מפושטת בלבד
# ==========================================

def test_pawn_moves_one_step_forward():
    pawn = piece(PAWN, WHITE, 3, 0)
    board = board_with(pawn)
    destinations = PawnRules.legal_destinations(board, pawn)
    assert Position(2, 0) in destinations


def test_pawn_can_double_step_from_start_row():
    pawn = piece(PAWN, WHITE, 6, 0)  # שורת ההתחלה בלוח 8x8
    board = board_with(pawn, width=8, height=8)
    destinations = PawnRules.legal_destinations(board, pawn)
    assert Position(4, 0) in destinations


def test_pawn_cannot_double_step_when_not_on_start_row():
    pawn = piece(PAWN, WHITE, 5, 0)  # כבר זז פעם - לא בשורת ההתחלה
    board = board_with(pawn, width=8, height=8)
    destinations = PawnRules.legal_destinations(board, pawn)
    assert Position(3, 0) not in destinations


def test_pawn_double_step_blocked_by_piece_in_between():
    pawn = piece(PAWN, WHITE, 6, 0)
    blocker = piece(PAWN, BLACK, 5, 0)
    board = board_with(pawn, blocker, width=8, height=8)
    destinations = PawnRules.legal_destinations(board, pawn)
    assert Position(4, 0) not in destinations


def test_pawn_double_step_blocked_by_piece_on_destination():
    pawn = piece(PAWN, WHITE, 6, 0)
    blocker = piece(PAWN, BLACK, 4, 0)
    board = board_with(pawn, blocker, width=8, height=8)
    destinations = PawnRules.legal_destinations(board, pawn)
    assert Position(4, 0) not in destinations


def test_pawn_captures_diagonally():
    pawn = piece(PAWN, WHITE, 2, 0)
    enemy = piece(PAWN, BLACK, 1, 1)
    board = board_with(pawn, enemy)
    destinations = PawnRules.legal_destinations(board, pawn)
    assert Position(1, 1) in destinations


def test_pawn_cannot_move_diagonally_onto_empty_cell():
    pawn = piece(PAWN, WHITE, 2, 0)
    board = board_with(pawn)
    destinations = PawnRules.legal_destinations(board, pawn)
    assert Position(1, 1) not in destinations


def test_pawn_cannot_capture_straight_ahead():
    pawn = piece(PAWN, WHITE, 2, 0)
    enemy = piece(PAWN, BLACK, 1, 0)
    board = board_with(pawn, enemy)
    destinations = PawnRules.legal_destinations(board, pawn)
    assert Position(1, 0) not in destinations


def test_black_pawn_moves_downward():
    pawn = piece(PAWN, BLACK, 1, 0)
    board = board_with(pawn)
    destinations = PawnRules.legal_destinations(board, pawn)
    assert Position(2, 0) in destinations


# ==========================================
# rules_for - הפניה לפי סוג כלי
# ==========================================

def test_rules_for_returns_the_matching_rule_class():
    assert rules_for(ROOK) is RookRules
    assert rules_for(PAWN) is PawnRules

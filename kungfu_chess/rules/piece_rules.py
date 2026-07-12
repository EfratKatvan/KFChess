from __future__ import annotations
from typing import Set

from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import Piece, WHITE, ROOK, BISHOP, QUEEN, KNIGHT, KING, PAWN
from kungfu_chess.model.position import Position

#עבור כלים שנעים בקו ישר/אלכסוני (צריח, רץ, מלכה), סורק במרחקים בלתי מוגבלים מהכלי והלאה בכל כיוון, עד חסימה (כולל אכילה).
#בודק את כל היעדים החוקיים
def _sliding_destinations(board: Board, piece: Piece, directions) -> Set[Position]:
    """סורק בקווים ישרים מהכלי והלאה בכל כיוון, עד חסימה (כולל אכילה)."""
    destinations: Set[Position] = set()
    for dr, dc in directions:
        row, col = piece.cell.row + dr, piece.cell.col + dc
        position = Position(row, col)
        while board.is_inside(position):
            occupant = board.piece_at(position)
            if occupant is None:
                destinations.add(position)
            else:
                if occupant.color != piece.color:
                    destinations.add(position)
                break
            row += dr
            col += dc
            position = Position(row, col)
    return destinations

#סורק את תאי היעד האפשריים עבור כלים שמבצעים "צעד" אחד בלבד (סוס, מלך) - לא סוריקה, אין חסימה בדרך.
#בודק את כל היעדים החוקיים עבור כלים שמבצעים צעד אחד בלבד (סוס, מלך).
def _step_destinations(board: Board, piece: Piece, offsets) -> Set[Position]:
    """בודק קבוצת תאי-יעד קבועים (סוס/מלך) - לא סוריקה, אין חסימה בדרך."""
    destinations: Set[Position] = set()
    for dr, dc in offsets:
        position = Position(piece.cell.row + dr, piece.cell.col + dc)
        if not board.is_inside(position):
            continue
        occupant = board.piece_at(position)
        if occupant is None or occupant.color != piece.color:
            destinations.add(position)
    return destinations


# 1. Rook - סורק ישר ומאונך עד חסימה
class RookRules:
    @staticmethod
    def legal_destinations(board: Board, piece: Piece) -> Set[Position]:
        return _sliding_destinations(board, piece, [(1, 0), (-1, 0), (0, 1), (0, -1)])


# 2. Bishop - סורק באלכסון עד חסימה
class BishopRules:
    @staticmethod
    def legal_destinations(board: Board, piece: Piece) -> Set[Position]:
        return _sliding_destinations(board, piece, [(1, 1), (1, -1), (-1, 1), (-1, -1)])


# 3. Queen - צירוף של צריח ורץ
class QueenRules:
    @staticmethod
    def legal_destinations(board: Board, piece: Piece) -> Set[Position]:
        return RookRules.legal_destinations(board, piece) | BishopRules.legal_destinations(board, piece)


# 4. Knight - קפיצות L, מתעלם מחסימות בדרך
class KnightRules:
    _OFFSETS = [(1, 2), (1, -2), (-1, 2), (-1, -2), (2, 1), (2, -1), (-2, 1), (-2, -1)]

    @staticmethod
    def legal_destinations(board: Board, piece: Piece) -> Set[Position]:
        return _step_destinations(board, piece, KnightRules._OFFSETS)


# 5. King - תא אחד לכל כיוון
class KingRules:
    _OFFSETS = [(dr, dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if (dr, dc) != (0, 0)]

    @staticmethod
    def legal_destinations(board: Board, piece: Piece) -> Set[Position]:
        return _step_destinations(board, piece, KingRules._OFFSETS)


def _pawn_start_row(board: Board, color: str) -> int:
    """שורת ההתחלה של חייל, לפי גובה הלוח (זהה להיגיון שהיה קיים מקודם)."""
    if color == WHITE:
        return board.height - 2 if board.height == 8 else board.height - 1
    return 1 if board.height == 8 else 0


# 6. Pawn - תנועה מפושטת: צעד אחד קדימה (או צעד כפול משורת ההתחלה),
# אכילה אלכסונית קדימה בלבד. אין en passant, אין הכתרה כאן (זה ב-RealTimeArbiter).
class PawnRules:
    @staticmethod
    def legal_destinations(board: Board, piece: Piece) -> Set[Position]:
        direction = -1 if piece.color == WHITE else 1
        destinations: Set[Position] = set()

        forward = Position(piece.cell.row + direction, piece.cell.col)
        if board.is_inside(forward) and board.piece_at(forward) is None:
            destinations.add(forward)

            if piece.cell.row == _pawn_start_row(board, piece.color):
                double_forward = Position(piece.cell.row + 2 * direction, piece.cell.col)
                if board.is_inside(double_forward) and board.piece_at(double_forward) is None:
                    destinations.add(double_forward)

        for dc in (-1, 1):
            diagonal = Position(piece.cell.row + direction, piece.cell.col + dc)
            if not board.is_inside(diagonal):
                continue
            occupant = board.piece_at(diagonal)
            if occupant is not None and occupant.color != piece.color:
                destinations.add(diagonal)

        return destinations


_RULES_BY_KIND = {
    ROOK: RookRules,
    BISHOP: BishopRules,
    QUEEN: QueenRules,
    KNIGHT: KnightRules,
    KING: KingRules,
    PAWN: PawnRules,
}


def rules_for(kind: str):
    return _RULES_BY_KIND[kind]

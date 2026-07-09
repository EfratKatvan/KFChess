from __future__ import annotations
from typing import Optional

from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import Piece, WHITE, KING, QUEEN, ROOK, BISHOP, KNIGHT, PAWN
from kungfu_chess.model.position import Position


def is_path_clear(board: Board, from_pos: Position, to_pos: Position) -> bool:
    """בודקת האם המסלול מתא המקור לתא היעד פנוי מכלים אחרים
    (רלוונטי למלכה, רץ, צריח)."""
    dr = to_pos.row - from_pos.row
    dc = to_pos.col - from_pos.col

    step_r = 0 if dr == 0 else (1 if dr > 0 else -1)
    step_c = 0 if dc == 0 else (1 if dc > 0 else -1)

    current = Position(from_pos.row + step_r, from_pos.col + step_c)
    while current != to_pos:
        if board.piece_at(current) is not None:
            return False
        current = Position(current.row + step_r, current.col + step_c)

    return True


def is_legal_pawn_move(piece: Piece, from_pos: Position, to_pos: Position, board: Board) -> bool:
    r1, c1 = from_pos.row, from_pos.col
    r2, c2 = to_pos.row, to_pos.col
    board_height = board.height
    target = board.piece_at(to_pos)

    if piece.color == WHITE:
        direction = -1
        start_row = board_height - 2 if board_height == 8 else board_height - 1
    else:
        direction = 1
        start_row = 1 if board_height == 8 else 0

    if c1 == c2:
        if r2 - r1 == direction and target is None:
            return True
        if r1 == start_row and r2 - r1 == 2 * direction:
            mid = board.piece_at(Position(r1 + direction, c1))
            if mid is None and target is None:
                return True

    if abs(c2 - c1) == 1 and r2 - r1 == direction:
        if target is not None and target.color != piece.color:
            return True

    return False


def is_legal_piece_move(
    piece: Piece,
    from_pos: Position,
    to_pos: Position,
    board: Optional[Board] = None,
) -> bool:
    # אם המקור והיעד זהים, אין תנועה חוקית
    if from_pos == to_pos:
        return False

    r1, c1 = from_pos.row, from_pos.col
    r2, c2 = to_pos.row, to_pos.col
    dr = abs(r2 - r1)
    dc = abs(c2 - c1)

    target = board.piece_at(to_pos) if board is not None else None
    # מנסה לאכול כלי מהקבוצה שלו-בצבע שלו
    if target is not None and target.color == piece.color:
        return False

    # אם זה מלך, הוא יכול לזוז רק תא אחד לכל כיוון
    if piece.kind == KING:
        return dr <= 1 and dc <= 1
    # אם זה צריח, הוא יכול לזוז רק ישר בעמודות או בשורות, ואם רוצה יותר ממקום אחד, הוא צריך לבדוק שהמסלול פנוי
    if piece.kind == ROOK:
        if r1 != r2 and c1 != c2:
            return False
        if board is not None and not is_path_clear(board, from_pos, to_pos):
            return False
        return True
    # אם זה רץ, הוא יכול לזוז רק באלכסון, ואם רוצה יותר ממקום אחד, הוא צריך לבדוק שהמסלול פנוי
    if piece.kind == BISHOP:
        if dr != dc:
            return False
        if board is not None and not is_path_clear(board, from_pos, to_pos):
            return False
        return True
    # אם זה מלכה, הוא יכול לזוז ישר או באלכסון, ואם רוצה יותר ממקום אחד, הוא צריך לבדוק שהמסלול פנוי
    if piece.kind == QUEEN:
        is_straight = (r1 == r2) or (c1 == c2)
        is_diagonal = dr == dc
        if not (is_straight or is_diagonal):
            return False
        if board is not None and not is_path_clear(board, from_pos, to_pos):
            return False
        return True
    # אם זה סוס, הוא יכול לזוז רק בתבנית של "L"
    if piece.kind == KNIGHT:
        return (dr == 1 and dc == 2) or (dr == 2 and dc == 1)
    # אם זה חייל, יש לו את חוקי התנועה/אכילה המיוחדים שלו - דורש לוח
    if piece.kind == PAWN:
        if board is None:
            return False
        return is_legal_pawn_move(piece, from_pos, to_pos, board)

    return False

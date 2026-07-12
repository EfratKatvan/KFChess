from __future__ import annotations
from dataclasses import dataclass

from kungfu_chess.model.board import Board
from kungfu_chess.model.position import Position

REASON_OUTSIDE_BOARD = "outside_board"
REASON_EMPTY_SOURCE = "empty_source"
REASON_FRIENDLY_DESTINATION = "friendly_destination"


@dataclass
class BoardCheck:
    is_valid: bool
    reason: str


class BoardRules:
    """חוקיות ברמת הלוח בלבד: גבולות ותפוסה - בלי שום ידיעה על צורת-התנועה
    של כלי ספציפי. נפרדת מ-RuleEngine (piece_rules) כדי ששתי האחריויות
    ייקראו, ייבדקו ויוחלפו בנפרד."""

    def check(self, board: Board, from_pos: Position, to_pos: Position) -> BoardCheck:
        if not board.is_inside(from_pos) or not board.is_inside(to_pos):
            return BoardCheck(False, REASON_OUTSIDE_BOARD)

        piece = board.piece_at(from_pos)
        if piece is None:
            return BoardCheck(False, REASON_EMPTY_SOURCE)

        target = board.piece_at(to_pos)
        if target is not None and target.color == piece.color:
            return BoardCheck(False, REASON_FRIENDLY_DESTINATION)

        return BoardCheck(True, "")

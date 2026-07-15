from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional, Protocol, Set

from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import KING, PAWN, QUEEN, WHITE, Piece
from kungfu_chess.model.position import Position
from kungfu_chess.rules.board_rules import (
    BoardRules,
    REASON_EMPTY_SOURCE,
    REASON_FRIENDLY_DESTINATION,
    REASON_OUTSIDE_BOARD,
)
from kungfu_chess.rules.piece_rules import PieceRule, STANDARD_PIECE_RULES

REASON_OK = "ok"
REASON_ILLEGAL_PIECE_MOVE = "illegal_piece_move"


@dataclass
class MoveValidation:
    is_valid: bool
    reason: str


class RuleEngine:
    """קריאה-בלבד: בהינתן תא מקור ותא יעד, האם הפקודה הזו חוקית כרגע?
    לא נוגע בלוח, לא מזיז כלים, לא יודע כלום על game_over."""

    def __init__(
        self,
        board: Board,
        piece_rules: Optional[Dict[str, PieceRule]] = None,
        board_rules: Optional[BoardRules] = None,
    ) -> None:
        self._board = board
        self._piece_rules = piece_rules if piece_rules is not None else STANDARD_PIECE_RULES
        self._board_rules = board_rules if board_rules is not None else BoardRules()

    def legal_destinations(self, from_pos: Position) -> Set[Position]:
        """כל היעדים החוקיים לכלי בתא הזה, לפי חוקי סוג-הכלי בלבד (כמו
        validate_move, אבל כל האפשרויות ביחד ולא בדיקת יעד בודד) - למשל
        להדגשה ויזואלית של יעדים אפשריים אחרי בחירת כלי. לא בודק חסימות
        זמן-אמת (מסלול/יעד תפוס) - זה תלוי-רגע ומשתנה כל הזמן, לא חלק
        מ"מה שחוקי לפי חוקי השחמט"."""
        piece = self._board.piece_at(from_pos)
        if piece is None:
            return set()
        rule = self._piece_rules.get(piece.kind)
        if rule is None:
            return set()
        return rule.legal_destinations(self._board, piece)

    def validate_move(self, from_pos: Position, to_pos: Position) -> MoveValidation:
        board_check = self._board_rules.check(self._board, from_pos, to_pos)
        if not board_check.is_valid:
            return MoveValidation(False, board_check.reason)

        #בודקת האם היעד שלי נמצא באחד מהיעדים החוקיים שאפשריים
        if to_pos not in self.legal_destinations(from_pos):
            return MoveValidation(False, REASON_ILLEGAL_PIECE_MOVE)

        return MoveValidation(True, REASON_OK)


class WinCondition(Protocol):
    """מחליטה מתי לכידה מסיימת את המשחק - ניתנת להחלפה כדי לתמוך בחוק
    ניצחון אחר (למשל: לכידת כל הצריחים) בלי לגעת ב-RealTimeArbiter."""

    def is_game_over(self, captured_piece: Optional[Piece]) -> bool: ...


class KingCaptureWinCondition:
    def is_game_over(self, captured_piece: Optional[Piece]) -> bool:
        return captured_piece is not None and captured_piece.kind == KING


class PromotionRule(Protocol):
    """מחליטה מה קורה לכלי בהגעה ליעדו - ניתנת להחלפה כדי לתמוך בחוק
    הכתרה אחר (למשל: הכתרה לצריח) בלי לגעת ב-RealTimeArbiter."""

    def promote(self, piece: Piece, board_height: int) -> None: ...


class LastRankPromotion:
    def promote(self, piece: Piece, board_height: int) -> None:
        if piece.kind != PAWN:
            return
        last_rank = 0 if piece.color == WHITE else board_height - 1
        if piece.cell.row == last_rank:
            piece.kind = QUEEN

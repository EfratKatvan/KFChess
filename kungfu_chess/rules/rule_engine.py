from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Protocol

from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import KING, PAWN, QUEEN, WHITE, Piece
from kungfu_chess.model.position import Position
from kungfu_chess.rules.piece_rules import rules_for

REASON_OK = "ok"
REASON_OUTSIDE_BOARD = "outside_board"
REASON_EMPTY_SOURCE = "empty_source"
REASON_FRIENDLY_DESTINATION = "friendly_destination"
REASON_ILLEGAL_PIECE_MOVE = "illegal_piece_move"


@dataclass
class MoveValidation:
    is_valid: bool
    reason: str


class RuleEngine:
    """קריאה-בלבד: בהינתן תא מקור ותא יעד, האם הפקודה הזו חוקית כרגע?
    לא נוגע בלוח, לא מזיז כלים, לא יודע כלום על game_over."""

    def __init__(self, board: Board) -> None:
        self._board = board

    def validate_move(self, from_pos: Position, to_pos: Position) -> MoveValidation:
        if not self._board.is_inside(from_pos) or not self._board.is_inside(to_pos):
            return MoveValidation(False, REASON_OUTSIDE_BOARD)

        piece = self._board.piece_at(from_pos)
        if piece is None:
            return MoveValidation(False, REASON_EMPTY_SOURCE)

        target = self._board.piece_at(to_pos)
        if target is not None and target.color == piece.color:
            return MoveValidation(False, REASON_FRIENDLY_DESTINATION)
        
        #בודקת האם היעד שלי נמצא באחד מהיעדים החוקיים שאפשריים
        rules = rules_for(piece.kind)
        if to_pos not in rules.legal_destinations(self._board, piece):
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

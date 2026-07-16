from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional, Protocol, Set

from kungfu_chess.model.board import BoardRepresentation
from kungfu_chess.model.piece import KING, PAWN, QUEEN, WHITE, PieceRepresentation
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
    """Read-only: given a source and destination cell, is this command
    legal right now? Never touches the board, never moves pieces, knows
    nothing about game_over."""

    def __init__(
        self,
        board: BoardRepresentation,
        piece_rules: Optional[Dict[str, PieceRule]] = None,
        board_rules: Optional[BoardRules] = None,
    ) -> None:
        self._board = board
        self._piece_rules = piece_rules if piece_rules is not None else STANDARD_PIECE_RULES
        self._board_rules = board_rules if board_rules is not None else BoardRules()

    def legal_destinations(self, from_pos: Position) -> Set[Position]:
        """Doesn't check real-time blocking (route/destination busy) -
        that's moment-dependent and constantly changing, not part of
        "what's legal by chess rules"."""
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

        if to_pos not in self.legal_destinations(from_pos):
            return MoveValidation(False, REASON_ILLEGAL_PIECE_MOVE)

        return MoveValidation(True, REASON_OK)


class WinCondition(Protocol):
    """Decides when a capture ends the game - swappable to support a
    different win condition (e.g. capturing all rooks) without touching
    RealTimeArbiter."""

    def is_game_over(self, captured_piece: Optional[PieceRepresentation]) -> bool: ...


class KingCaptureWinCondition:
    def is_game_over(self, captured_piece: Optional[PieceRepresentation]) -> bool:
        return captured_piece is not None and captured_piece.kind == KING


class PromotionRule(Protocol):
    """Decides what happens to a piece on arrival at its destination -
    swappable to support a different promotion rule (e.g. promoting to
    a rook) without touching RealTimeArbiter."""

    def promote(self, piece: PieceRepresentation, board_height: int) -> None: ...


class LastRankPromotion:
    def promote(self, piece: PieceRepresentation, board_height: int) -> None:
        if piece.kind != PAWN:
            return
        last_rank = 0 if piece.color == WHITE else board_height - 1
        if piece.cell.row == last_rank:
            piece.kind = QUEEN

from __future__ import annotations

from kungfu_chess.model.board import Board
from kungfu_chess.model.position import Position
from kungfu_chess.rules.piece_rules import is_legal_piece_move


class RuleEngine:
    """ולידציה בלבד (read-only) של מהלך מבוקש, מול המצב הנוכחי של הלוח."""

    def __init__(self, board: Board) -> None:
        self._board = board

    def is_legal_move(self, from_pos: Position, to_pos: Position) -> bool:
        piece = self._board.piece_at(from_pos)
        if piece is None:
            return False
        return is_legal_piece_move(piece, from_pos, to_pos, self._board)

from __future__ import annotations
from typing import Tuple

from kungfu_chess.model.board import Board
from kungfu_chess.rules.piece_rules import is_legal_piece_move


class RuleEngine:
    """ולידציה בלבד (read-only) של מהלך מבוקש, מול המצב הנוכחי של הלוח."""

    def __init__(self, board: Board) -> None:
        self._board = board

    def is_legal_move(
        self, piece_token: str, from_pos: Tuple[int, int], to_pos: Tuple[int, int]
    ) -> bool:
        target_token = self._board.get_cell(*to_pos)
        return is_legal_piece_move(
            piece_token, from_pos, to_pos, self._board.to_rows(), target_token
        )

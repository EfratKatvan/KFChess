from __future__ import annotations
from typing import Optional, Tuple

from kungfu_chess.model.board import Board

CELL_SIZE = 100


class BoardMapper:
    """ממיר קואורדינטת פיקסלים לתא לוגי על הלוח (row, col)."""

    def __init__(self, board: Board, cell_size: int = CELL_SIZE) -> None:
        self._board = board
        self._cell_size = cell_size
    #פונקציה שמקבלת קואורדינטות פיקסלים ומחזירה את התא המתאים בלוח (row, col) או None אם מחוץ ללוח
    def to_cell(self, x: int, y: int) -> Optional[Tuple[int, int]]:
        col = x // self._cell_size
        row = y // self._cell_size
        if not self._board.is_inside(row, col):
            return None
        return row, col

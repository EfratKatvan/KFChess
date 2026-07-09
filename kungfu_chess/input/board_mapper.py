from __future__ import annotations
from typing import Optional

from kungfu_chess.model.board import Board
from kungfu_chess.model.position import Position

CELL_SIZE = 100


class BoardMapper:
    """ממיר קואורדינטת פיקסלים לתא לוגי על הלוח (Position)."""

    def __init__(self, board: Board, cell_size: int = CELL_SIZE) -> None:
        self._board = board
        self._cell_size = cell_size

    #פונקציה שמקבלת קואורדינטות פיקסלים ומחזירה את התא המתאים בלוח (Position) או None אם מחוץ ללוח
    def to_cell(self, x: int, y: int) -> Optional[Position]:
        col = x // self._cell_size
        row = y // self._cell_size
        position = Position(row, col)
        if not self._board.is_inside(position):
            return None
        return position

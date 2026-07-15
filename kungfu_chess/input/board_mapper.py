from __future__ import annotations
from typing import Optional

from kungfu_chess.model.board import Board
from kungfu_chess.model.position import Position

CELL_SIZE = 100


class BoardMapper:
    """ממיר קואורדינטת פיקסלים לתא לוגי על הלוח (Position).

    y_offset - כמה פיקסלים הלוח מוזח כלפי מטה בקנבס (למשל רצועת ה-HUD
    שהרנדרר מצייר מעל הלוח, ר' view/renderer.py:HUD_HEIGHT). ברירת המחדל
    0 שומרת על ההתנהגות המקורית לכל צרכן שלא מרנדר HUD (טסטים, זרימת
    הטקסט)."""

    def __init__(self, board: Board, cell_size: int = CELL_SIZE, y_offset: int = 0) -> None:
        self._board = board
        self._cell_size = cell_size
        self._y_offset = y_offset

    #פונקציה שמקבלת קואורדינטות פיקסלים ומחזירה את התא המתאים בלוח (Position) או None אם מחוץ ללוח
    def to_cell(self, x: int, y: int) -> Optional[Position]:
        y -= self._y_offset
        if y < 0:
            return None
        col = x // self._cell_size
        row = y // self._cell_size
        position = Position(row, col)
        if not self._board.is_inside(position):
            return None
        return position

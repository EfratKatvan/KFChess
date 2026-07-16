from __future__ import annotations
from typing import Optional

from kungfu_chess.model.board import Board
from kungfu_chess.model.position import Position

CELL_SIZE = 100


class BoardMapper:
    """Converts a pixel coordinate to a logical board cell (Position).

    x_offset/y_offset - how many pixels the board is shifted right/down
    on the canvas (e.g. the side panels the renderer draws around the
    board, see view/renderer.py:SIDE_PANEL_WIDTH). The defaults of 0
    preserve the original behavior for any consumer that doesn't render
    those panels (tests, the text flow)."""

    def __init__(self, board: Board, cell_size: int = CELL_SIZE, x_offset: int = 0, y_offset: int = 0) -> None:
        self._board = board
        self._cell_size = cell_size
        self._x_offset = x_offset
        self._y_offset = y_offset

    def to_cell(self, x: int, y: int) -> Optional[Position]:
        x -= self._x_offset
        y -= self._y_offset
        if x < 0 or y < 0:
            return None
        col = x // self._cell_size
        row = y // self._cell_size
        position = Position(row, col)
        if not self._board.is_inside(position):
            return None
        return position

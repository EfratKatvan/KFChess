from __future__ import annotations

from typing import Dict, Tuple

from kungfu_chess.assets_config import ASSETS_DIR
from kungfu_chess.model.position import Position
from kungfu_chess.view.img import Img

BOARD_IMAGE_PATH = ASSETS_DIR / "board.png"


class BoardView:
    """Injected from outside instead of module-level global state, for
    the same reason as AnimationCache."""

    def __init__(self) -> None:
        self._backgrounds: Dict[Tuple[int, int, int], Img] = {}

    def new_canvas(self, board_width: int, board_height: int, cell_size: int) -> Img:
        """A fresh copy of the board background - must not return the
        cached image itself, since drawing pieces onto it would
        contaminate the cache for later frames."""
        background = self._background(board_width, board_height, cell_size)
        canvas = Img()
        canvas.img = background.img.copy()
        return canvas

    def _background(self, board_width: int, board_height: int, cell_size: int) -> Img:
        key = (board_width, board_height, cell_size)
        cached = self._backgrounds.get(key)
        if cached is not None:
            return cached

        background = Img().read(BOARD_IMAGE_PATH, size=(board_width * cell_size, board_height * cell_size))
        self._backgrounds[key] = background
        return background

    @staticmethod
    def cell_to_pixel(position: Position, cell_size: int) -> Tuple[int, int]:
        return position.col * cell_size, position.row * cell_size

    @staticmethod
    def lerp_pixel(source: Position, destination: Position, progress: float, cell_size: int) -> Tuple[int, int]:
        sx, sy = BoardView.cell_to_pixel(source, cell_size)
        dx, dy = BoardView.cell_to_pixel(destination, cell_size)
        return int(sx + (dx - sx) * progress), int(sy + (dy - sy) * progress)

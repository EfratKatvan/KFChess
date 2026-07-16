from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

import numpy as np

from kungfu_chess.assets_config import DEFAULT_PIECE_SET, asset_code
from kungfu_chess.engine.board_view_state import BoardViewState
from kungfu_chess.input.board_mapper import CELL_SIZE
from kungfu_chess.model.piece import WHITE, BLACK
from kungfu_chess.model.position import Position
from kungfu_chess.view.animation import AnimationCache, frame_index
from kungfu_chess.view.board_view import BoardView
from kungfu_chess.view.img import Img

# Semi-transparent ice-blue (BGRA) - the "hourglass" drawn over a piece frozen in cooldown.
COOLDOWN_OVERLAY_COLOR_BGRA = (235, 206, 135, 120)

# Gold border - highlights the currently selected cell (Controller.selected_pos).
SELECTION_HIGHLIGHT_COLOR_BGRA = (0, 215, 255, 255)
SELECTION_HIGHLIGHT_THICKNESS = 4

# Semi-transparent green - fills every legal destination cell for the selected piece (RuleEngine.legal_destinations).
DESTINATION_HIGHLIGHT_COLOR_BGRA = (60, 200, 60, 130)

# HUD strip above and below the board - score per color (BoardViewState.scores).
# Intentionally not part of the board itself (BoardView) - it's an addition
# from the Renderer, not part of "what the board looks like".
HUD_HEIGHT = 60
HUD_BACKGROUND_COLOR_BGRA = (40, 40, 40, 255)
HUD_TEXT_COLOR_BGRA = (255, 255, 255, 255)
HUD_FONT_SIZE = 0.9
HUD_TEXT_THICKNESS = 2

# Thin divider line between the HUD strip and the board itself - visually distinguishes without being loud.
HUD_DIVIDER_COLOR_BGRA = (90, 90, 90, 255)
HUD_DIVIDER_THICKNESS = 2


def _blend_solid_rect(canvas: Img, x: int, y: int, width: int, height: int, color_bgra) -> None:
    """Blends (with real alpha blending, see Img.draw_on) a solid-color
    rectangle onto the canvas - the shared basis for the hourglass and
    for tinting legal destinations."""
    overlay = Img()
    overlay.img = np.full((height, width, 4), color_bgra, dtype=np.uint8)
    overlay.draw_on(canvas, x, y)


def _draw_cooldown_overlay(canvas: Img, pixel_pos: Tuple[int, int], remaining_fraction: float, cell_size: int) -> None:
    """"Hourglass": a semi-transparent ice-blue flood covering a shrinking
    part of the cell - full when the cooldown starts, and gone entirely
    (the piece "frees up") when it ends. The "sand" drains from the top -
    the flood's top edge drops over time, and the remaining "sand"
    settles downward until it's gone."""
    if remaining_fraction <= 0:
        return
    overlay_height = max(1, round(cell_size * remaining_fraction))
    x, y = pixel_pos
    _blend_solid_rect(canvas, x, y + (cell_size - overlay_height), cell_size, overlay_height, COOLDOWN_OVERLAY_COLOR_BGRA)


def _draw_selection_highlight(canvas: Img, pixel_pos: Tuple[int, int], cell_size: int) -> None:
    x, y = pixel_pos
    canvas.draw_rect(x, y, cell_size, cell_size, SELECTION_HIGHLIGHT_COLOR_BGRA, SELECTION_HIGHLIGHT_THICKNESS)


def _draw_destination_highlight(canvas: Img, pixel_pos: Tuple[int, int], cell_size: int) -> None:
    x, y = pixel_pos
    _blend_solid_rect(canvas, x, y, cell_size, cell_size, DESTINATION_HIGHLIGHT_COLOR_BGRA)


def _cell_pixel_pos(position: Position, cell_size: int) -> Tuple[int, int]:
    """Converts a logical cell to a pixel on the full canvas (including
    the top HUD strip) - a single point that applies the HUD offset, so
    there aren't several copies of the same +HUD_HEIGHT scattered across
    draw() (exactly the kind of duplication that once caused the gap
    between click mapping and actual rendering)."""
    x, y = BoardView.cell_to_pixel(position, cell_size)
    return x, y + HUD_HEIGHT


def _draw_centered_text(canvas: Img, text: str, center_x: int, center_y: int) -> None:
    """Centers text horizontally around center_x and vertically around
    center_y - instead of drawing from a fixed corner, so the score sits
    in the middle of the HUD strip instead of sticking to one side."""
    width, height = canvas.text_size(text, HUD_FONT_SIZE, HUD_TEXT_THICKNESS)
    x = center_x - width // 2
    y = center_y + height // 2
    canvas.put_text(text, x, y, HUD_FONT_SIZE, HUD_TEXT_COLOR_BGRA, HUD_TEXT_THICKNESS)


def _draw_score_hud(canvas: Img, scores: Dict[str, int], board_pixel_width: int, board_pixel_height: int) -> None:
    center_x = board_pixel_width // 2
    _draw_centered_text(canvas, f"Black: {scores.get(BLACK, 0)}", center_x, HUD_HEIGHT // 2)
    _draw_centered_text(
        canvas, f"White: {scores.get(WHITE, 0)}", center_x, HUD_HEIGHT + board_pixel_height + HUD_HEIGHT // 2,
    )
    _blend_solid_rect(canvas, 0, HUD_HEIGHT - HUD_DIVIDER_THICKNESS, board_pixel_width, HUD_DIVIDER_THICKNESS, HUD_DIVIDER_COLOR_BGRA)
    _blend_solid_rect(canvas, 0, HUD_HEIGHT + board_pixel_height, board_pixel_width, HUD_DIVIDER_THICKNESS, HUD_DIVIDER_COLOR_BGRA)


class Renderer:
    """Works from BoardViewState alone (the "display board" separate from
    the real Board, see engine/board_view_state.py) - no knowledge here
    of Motion/Jump/Cooldown/Piece.state, all visual state already
    arrives pre-resolved on every PieceView. animation_cache and
    board_view are injected (not module-level global state) so every
    consumer - image_view in a real run, or a test - holds its own
    cache, with no leaking between runs."""

    def __init__(self, animation_cache: Optional[AnimationCache] = None, board_view: Optional[BoardView] = None) -> None:
        self._animation_cache = animation_cache if animation_cache is not None else AnimationCache()
        self._board_view = board_view if board_view is not None else BoardView()

    def draw(
        self,
        view_state: BoardViewState,
        cell_size: int = CELL_SIZE,
        piece_set: str = DEFAULT_PIECE_SET,
        selected_position: Optional[Position] = None,
        legal_destinations: Optional[Iterable[Position]] = None,
    ) -> Img:
        """Pure logic - opens no window and never touches input, so it
        stays unit-testable. selected_position/legal_destinations are
        intentionally not part of BoardViewState - those are choices/
        queries on the view/input side, not the game's own state."""
        board_pixel_width = view_state.width * cell_size
        board_pixel_height = view_state.height * cell_size

        canvas = Img()
        canvas.img = np.full(
            (board_pixel_height + 2 * HUD_HEIGHT, board_pixel_width, 4), HUD_BACKGROUND_COLOR_BGRA, dtype=np.uint8
        )
        board_background = self._board_view.new_canvas(view_state.width, view_state.height, cell_size)
        board_background.draw_on(canvas, 0, HUD_HEIGHT)

        for piece_view in view_state.pieces:
            if piece_view.target_position is not None and piece_view.progress is not None:
                x, y = BoardView.lerp_pixel(
                    piece_view.position, piece_view.target_position, piece_view.progress, cell_size
                )
                pixel_pos = (x, y + HUD_HEIGHT)
            else:
                pixel_pos = _cell_pixel_pos(piece_view.position, cell_size)

            code = asset_code(piece_view.color, piece_view.kind)
            animation = self._animation_cache.load(code, piece_view.visual_state, cell_size, piece_set)
            frame = animation.frames[frame_index(piece_view.elapsed_ms, animation)]
            frame.draw_on(canvas, *pixel_pos)

            if piece_view.remaining_fraction is not None:
                _draw_cooldown_overlay(canvas, pixel_pos, piece_view.remaining_fraction, cell_size)

        if selected_position is not None:
            _draw_selection_highlight(canvas, _cell_pixel_pos(selected_position, cell_size), cell_size)

        if legal_destinations is not None:
            for destination in legal_destinations:
                _draw_destination_highlight(canvas, _cell_pixel_pos(destination, cell_size), cell_size)

        _draw_score_hud(canvas, view_state.scores, board_pixel_width, board_pixel_height)

        return canvas

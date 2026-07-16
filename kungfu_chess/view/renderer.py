from __future__ import annotations

from typing import Iterable, Optional, Tuple

import numpy as np

from kungfu_chess.assets_config import DEFAULT_PIECE_SET, asset_code
from kungfu_chess.engine.board_view_state import BoardViewState, MoveLogEntry, PieceView
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

# Semi-transparent red - fills a legal destination cell that also holds a capturable enemy piece.
CAPTURE_HIGHLIGHT_COLOR_BGRA = (50, 50, 220, 150)

# Red border - flashes on a cell the player clicked as a move target while
# it was actually illegal for the selected piece (not just switching
# selection to another friendly piece, which isn't an error).
INVALID_TARGET_HIGHLIGHT_COLOR_BGRA = (0, 0, 255, 255)
INVALID_TARGET_HIGHLIGHT_THICKNESS = 4

# Bold white text over a dimmed band across the board once the game ends.
GAME_OVER_TEXT = "GAME OVER"
GAME_OVER_TEXT_COLOR_BGRA = (255, 255, 255, 255)
GAME_OVER_FONT_SIZE = 2.0
GAME_OVER_THICKNESS = 4
GAME_OVER_BAND_HEIGHT = 90
GAME_OVER_BAND_COLOR_BGRA = (20, 20, 20, 190)

# Side panels flanking the board - one per team, with the running score
# and a chronological move log (BoardViewState.scores / move_log).
# Intentionally not part of the board itself (BoardView) - an addition
# from the Renderer, not part of "what the board looks like".
SIDE_PANEL_WIDTH = 220
SIDE_PANEL_BACKGROUND_COLOR_BGRA = (40, 40, 40, 255)
SIDE_PANEL_TEXT_COLOR_BGRA = (255, 255, 255, 255)
SIDE_PANEL_ACCENT_COLOR_BGRA = (0, 255, 255, 255)  # plain yellow - distinct from SELECTION_HIGHLIGHT_COLOR_BGRA's gold
SIDE_PANEL_HEADER_FONT_SIZE = 0.7
SIDE_PANEL_HEADER_THICKNESS = 2
SIDE_PANEL_ROW_FONT_SIZE = 0.5
SIDE_PANEL_ROW_THICKNESS = 1

SIDE_PANEL_TEAM_LABEL_Y = 26
SIDE_PANEL_SCORE_Y = 56
SIDE_PANEL_COLUMNS_Y = 84
SIDE_PANEL_ROWS_START_Y = 106
SIDE_PANEL_ROW_HEIGHT = 20
SIDE_PANEL_PADDING = 12
SIDE_PANEL_MOVE_COLUMN_FRACTION = 0.45  # how far across the panel the "Move" column starts

# Thin divider line between each side panel and the board itself.
SIDE_PANEL_DIVIDER_COLOR_BGRA = (90, 90, 90, 255)
SIDE_PANEL_DIVIDER_THICKNESS = 2


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


def _draw_border_highlight(canvas: Img, pixel_pos: Tuple[int, int], cell_size: int, color_bgra, thickness: int) -> None:
    x, y = pixel_pos
    canvas.draw_rect(x, y, cell_size, cell_size, color_bgra, thickness)


def _draw_selection_highlight(canvas: Img, pixel_pos: Tuple[int, int], cell_size: int) -> None:
    _draw_border_highlight(canvas, pixel_pos, cell_size, SELECTION_HIGHLIGHT_COLOR_BGRA, SELECTION_HIGHLIGHT_THICKNESS)


def _draw_invalid_target_highlight(canvas: Img, pixel_pos: Tuple[int, int], cell_size: int) -> None:
    _draw_border_highlight(canvas, pixel_pos, cell_size, INVALID_TARGET_HIGHLIGHT_COLOR_BGRA, INVALID_TARGET_HIGHLIGHT_THICKNESS)


def _draw_destination_highlight(canvas: Img, pixel_pos: Tuple[int, int], cell_size: int, color_bgra=DESTINATION_HIGHLIGHT_COLOR_BGRA) -> None:
    x, y = pixel_pos
    _blend_solid_rect(canvas, x, y, cell_size, cell_size, color_bgra)


def _piece_at(view_state: BoardViewState, position: Position) -> Optional[PieceView]:
    for piece_view in view_state.pieces:
        if piece_view.position == position:
            return piece_view
    return None


def _draw_game_over_overlay(canvas: Img, board_x: int, board_pixel_width: int, board_pixel_height: int) -> None:
    band_y = (board_pixel_height - GAME_OVER_BAND_HEIGHT) // 2
    _blend_solid_rect(canvas, board_x, band_y, board_pixel_width, GAME_OVER_BAND_HEIGHT, GAME_OVER_BAND_COLOR_BGRA)
    _draw_centered_text(
        canvas, GAME_OVER_TEXT, board_x + board_pixel_width // 2, band_y + GAME_OVER_BAND_HEIGHT // 2,
        GAME_OVER_FONT_SIZE, GAME_OVER_TEXT_COLOR_BGRA, GAME_OVER_THICKNESS,
    )


def _cell_pixel_pos(position: Position, cell_size: int) -> Tuple[int, int]:
    """Converts a logical cell to a pixel on the full canvas (including
    the left side panel) - a single point that applies the panel offset,
    so there aren't several copies of the same +SIDE_PANEL_WIDTH
    scattered across draw() (exactly the kind of duplication that once
    caused the gap between click mapping and actual rendering)."""
    x, y = BoardView.cell_to_pixel(position, cell_size)
    return x + SIDE_PANEL_WIDTH, y


def _draw_centered_text(canvas: Img, text: str, center_x: int, center_y: int, font_size: float, color_bgra, thickness: int) -> None:
    """Centers text horizontally around center_x and vertically around
    center_y - instead of drawing from a fixed corner."""
    width, height = canvas.text_size(text, font_size, thickness)
    x = center_x - width // 2
    y = center_y + height // 2
    canvas.put_text(text, x, y, font_size, color_bgra, thickness)


def _square_name(position: Position, board_height: int) -> str:
    """Board-notation square name (e.g. "e2") - column becomes a letter,
    row is flipped so row 0 (the far/top row, as laid out in
    io/board_parser starting positions) reads as the highest rank."""
    file_letter = chr(ord("a") + position.col)
    rank_number = board_height - position.row
    return f"{file_letter}{rank_number}"


def _format_elapsed(elapsed_ms: int) -> str:
    total_seconds = elapsed_ms // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def _draw_side_panel(
    canvas: Img,
    x: int,
    panel_height: int,
    team_label: str,
    score: int,
    entries: Tuple[MoveLogEntry, ...],
    board_height: int,
) -> None:
    _blend_solid_rect(canvas, x, 0, SIDE_PANEL_WIDTH, panel_height, SIDE_PANEL_BACKGROUND_COLOR_BGRA)

    center_x = x + SIDE_PANEL_WIDTH // 2
    _draw_centered_text(
        canvas, team_label, center_x, SIDE_PANEL_TEAM_LABEL_Y,
        SIDE_PANEL_HEADER_FONT_SIZE, SIDE_PANEL_TEXT_COLOR_BGRA, SIDE_PANEL_HEADER_THICKNESS,
    )
    _draw_centered_text(
        canvas, f"Score: {score}", center_x, SIDE_PANEL_SCORE_Y,
        SIDE_PANEL_HEADER_FONT_SIZE, SIDE_PANEL_ACCENT_COLOR_BGRA, SIDE_PANEL_HEADER_THICKNESS,
    )

    time_column_x = x + SIDE_PANEL_PADDING
    move_column_x = x + round(SIDE_PANEL_WIDTH * SIDE_PANEL_MOVE_COLUMN_FRACTION)
    canvas.put_text("Time", time_column_x, SIDE_PANEL_COLUMNS_Y, SIDE_PANEL_ROW_FONT_SIZE, SIDE_PANEL_ACCENT_COLOR_BGRA, SIDE_PANEL_ROW_THICKNESS)
    canvas.put_text("Move", move_column_x, SIDE_PANEL_COLUMNS_Y, SIDE_PANEL_ROW_FONT_SIZE, SIDE_PANEL_ACCENT_COLOR_BGRA, SIDE_PANEL_ROW_THICKNESS)

    max_rows = max(0, (panel_height - SIDE_PANEL_ROWS_START_Y) // SIDE_PANEL_ROW_HEIGHT)
    for row_index, entry in enumerate(entries[-max_rows:] if max_rows else ()):
        row_y = SIDE_PANEL_ROWS_START_Y + row_index * SIDE_PANEL_ROW_HEIGHT
        move_text = f"{_square_name(entry.from_pos, board_height)}-{_square_name(entry.to_pos, board_height)}"
        canvas.put_text(_format_elapsed(entry.elapsed_ms), time_column_x, row_y, SIDE_PANEL_ROW_FONT_SIZE, SIDE_PANEL_TEXT_COLOR_BGRA, SIDE_PANEL_ROW_THICKNESS)
        canvas.put_text(move_text, move_column_x, row_y, SIDE_PANEL_ROW_FONT_SIZE, SIDE_PANEL_TEXT_COLOR_BGRA, SIDE_PANEL_ROW_THICKNESS)


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
        invalid_target: Optional[Position] = None,
    ) -> Img:
        """Pure logic - opens no window and never touches input, so it
        stays unit-testable. selected_position/legal_destinations are
        intentionally not part of BoardViewState - those are choices/
        queries on the view/input side, not the game's own state."""
        board_pixel_width = view_state.width * cell_size
        board_pixel_height = view_state.height * cell_size
        canvas_width = 2 * SIDE_PANEL_WIDTH + board_pixel_width

        canvas = Img()
        canvas.img = np.full(
            (board_pixel_height, canvas_width, 4), SIDE_PANEL_BACKGROUND_COLOR_BGRA, dtype=np.uint8
        )
        board_background = self._board_view.new_canvas(view_state.width, view_state.height, cell_size)
        board_background.draw_on(canvas, SIDE_PANEL_WIDTH, 0)

        for piece_view in view_state.pieces:
            if piece_view.target_position is not None and piece_view.progress is not None:
                x, y = BoardView.lerp_pixel(
                    piece_view.position, piece_view.target_position, piece_view.progress, cell_size
                )
                pixel_pos = (x + SIDE_PANEL_WIDTH, y)
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
            selected_piece = _piece_at(view_state, selected_position) if selected_position is not None else None
            for destination in legal_destinations:
                occupant = _piece_at(view_state, destination)
                is_capturable = (
                    occupant is not None and selected_piece is not None and occupant.color != selected_piece.color
                )
                color_bgra = CAPTURE_HIGHLIGHT_COLOR_BGRA if is_capturable else DESTINATION_HIGHLIGHT_COLOR_BGRA
                _draw_destination_highlight(canvas, _cell_pixel_pos(destination, cell_size), cell_size, color_bgra)

        if invalid_target is not None:
            _draw_invalid_target_highlight(canvas, _cell_pixel_pos(invalid_target, cell_size), cell_size)

        if view_state.game_over:
            _draw_game_over_overlay(canvas, SIDE_PANEL_WIDTH, board_pixel_width, board_pixel_height)

        _draw_side_panel(
            canvas, 0, board_pixel_height, "Black",
            view_state.scores.get(BLACK, 0), view_state.move_log.get(BLACK, ()), view_state.height,
        )
        _draw_side_panel(
            canvas, SIDE_PANEL_WIDTH + board_pixel_width, board_pixel_height, "White",
            view_state.scores.get(WHITE, 0), view_state.move_log.get(WHITE, ()), view_state.height,
        )
        _blend_solid_rect(canvas, SIDE_PANEL_WIDTH - SIDE_PANEL_DIVIDER_THICKNESS, 0, SIDE_PANEL_DIVIDER_THICKNESS, board_pixel_height, SIDE_PANEL_DIVIDER_COLOR_BGRA)
        _blend_solid_rect(canvas, SIDE_PANEL_WIDTH + board_pixel_width, 0, SIDE_PANEL_DIVIDER_THICKNESS, board_pixel_height, SIDE_PANEL_DIVIDER_COLOR_BGRA)

        return canvas

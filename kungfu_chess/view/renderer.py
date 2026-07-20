from __future__ import annotations

from typing import Iterable, Optional, Tuple

import numpy as np

from kungfu_chess.assets_config import DEFAULT_PIECE_SET, asset_code
from kungfu_chess.engine.board_view_state import BoardViewState, MoveLogEntry, PieceView
from kungfu_chess.input.board_mapper import CELL_SIZE
from kungfu_chess.model.piece import WHITE, BLACK, KING, QUEEN, ROOK, BISHOP, KNIGHT
from kungfu_chess.model.position import Position
from kungfu_chess.view.animation import AnimationCache, frame_index
from kungfu_chess.view.board_view import BoardView
from kungfu_chess.view.img import Img
from kungfu_chess.view.renderer_style import (
    CAPTURE_HIGHLIGHT_COLOR_BGRA,
    COOLDOWN_OVERLAY_COLOR_BGRA,
    DESTINATION_HIGHLIGHT_COLOR_BGRA,
    GAME_OVER_BAND_COLOR_BGRA,
    GAME_OVER_BAND_HEIGHT,
    GAME_OVER_BUTTON_BORDER_COLOR_BGRA,
    GAME_OVER_BUTTON_BORDER_THICKNESS,
    GAME_OVER_BUTTON_COLOR_BGRA,
    GAME_OVER_BUTTON_FONT_SIZE,
    GAME_OVER_BUTTON_HEIGHT,
    GAME_OVER_BUTTON_OFFSET_Y,
    GAME_OVER_BUTTON_TEXT,
    GAME_OVER_BUTTON_TEXT_THICKNESS,
    GAME_OVER_BUTTON_WIDTH,
    GAME_OVER_FONT_SIZE,
    GAME_OVER_HINT_FONT_SIZE,
    GAME_OVER_HINT_OFFSET_Y,
    GAME_OVER_HINT_TEXT,
    GAME_OVER_HINT_THICKNESS,
    GAME_OVER_TEXT,
    GAME_OVER_TEXT_COLOR_BGRA,
    GAME_OVER_THICKNESS,
    GAME_OVER_TITLE_OFFSET_Y,
    INVALID_TARGET_HIGHLIGHT_COLOR_BGRA,
    INVALID_TARGET_HIGHLIGHT_THICKNESS,
    SELECTION_HIGHLIGHT_COLOR_BGRA,
    SELECTION_HIGHLIGHT_THICKNESS,
    SIDE_PANEL_ACCENT_COLOR_BGRA,
    SIDE_PANEL_BACKGROUND_COLOR_BGRA,
    SIDE_PANEL_COLUMNS_Y,
    SIDE_PANEL_DIVIDER_COLOR_BGRA,
    SIDE_PANEL_DIVIDER_THICKNESS,
    SIDE_PANEL_HEADER_FONT_SIZE,
    SIDE_PANEL_HEADER_THICKNESS,
    SIDE_PANEL_MOVE_COLUMN_FRACTION,
    SIDE_PANEL_PADDING,
    SIDE_PANEL_ROW_FONT_SIZE,
    SIDE_PANEL_ROW_HEIGHT,
    SIDE_PANEL_ROW_THICKNESS,
    SIDE_PANEL_ROWS_START_Y,
    SIDE_PANEL_SCORE_Y,
    SIDE_PANEL_TEAM_LABEL_Y,
    SIDE_PANEL_TEXT_COLOR_BGRA,
    SIDE_PANEL_WIDTH,
)


def side_panel_width_for(cell_size: int) -> int:
    return round(SIDE_PANEL_WIDTH / CELL_SIZE * cell_size)


def _blend_solid_rect(canvas: Img, x: int, y: int, width: int, height: int, color_bgra) -> None:
    overlay = Img()
    overlay.img = np.full((height, width, 4), color_bgra, dtype=np.uint8)
    overlay.draw_on(canvas, x, y)


def _draw_cooldown_overlay(canvas: Img, pixel_pos: Tuple[int, int], remaining_fraction: float, cell_size: int) -> None:
    """Draws the "hourglass" overlay over a piece on cooldown: a
    semi-transparent rectangle whose height shrinks as remaining_fraction
    drops, so it looks like it's draining away."""
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


def game_over_button_rect(board_width: int, board_height: int, cell_size: int) -> Tuple[int, int, int, int]:
    """Computes the New Game button's rectangle (x, y, width, height) in
    canvas pixels. Used both to draw the button and, in image_view.py,
    to hit-test clicks against it."""
    board_pixel_width = board_width * cell_size
    board_pixel_height = board_height * cell_size
    band_y = (board_pixel_height - GAME_OVER_BAND_HEIGHT) // 2
    center_x = side_panel_width_for(cell_size) + board_pixel_width // 2
    button_center_y = band_y + GAME_OVER_BUTTON_OFFSET_Y
    return (
        center_x - GAME_OVER_BUTTON_WIDTH // 2,
        button_center_y - GAME_OVER_BUTTON_HEIGHT // 2,
        GAME_OVER_BUTTON_WIDTH,
        GAME_OVER_BUTTON_HEIGHT,
    )


def _faded(color_bgra, progress: float):
    r, g, b, a = color_bgra
    return (r, g, b, int(a * max(0.0, min(1.0, progress))))


def _draw_game_over_overlay(canvas: Img, view_state: BoardViewState, cell_size: int, progress: float = 1.0) -> None:
    """progress (0..1) animates the dimming band fading in; the title,
    button and hint only appear once progress reaches 1 - text can't be
    alpha-blended the way the band's solid rect can (put_text draws
    straight onto the canvas), so it pops in at the end of the fade
    instead of fading itself."""
    board_pixel_width = view_state.width * cell_size
    board_pixel_height = view_state.height * cell_size
    band_y = (board_pixel_height - GAME_OVER_BAND_HEIGHT) // 2
    side_panel_width = side_panel_width_for(cell_size)
    center_x = side_panel_width + board_pixel_width // 2

    _blend_solid_rect(canvas, side_panel_width, band_y, board_pixel_width, GAME_OVER_BAND_HEIGHT, _faded(GAME_OVER_BAND_COLOR_BGRA, progress))
    if progress < 1.0:
        return

    _draw_centered_text(
        canvas, GAME_OVER_TEXT, center_x, band_y + GAME_OVER_TITLE_OFFSET_Y,
        GAME_OVER_FONT_SIZE, GAME_OVER_TEXT_COLOR_BGRA, GAME_OVER_THICKNESS,
    )

    button_x, button_y, button_w, button_h = game_over_button_rect(view_state.width, view_state.height, cell_size)
    _blend_solid_rect(canvas, button_x, button_y, button_w, button_h, GAME_OVER_BUTTON_COLOR_BGRA)
    canvas.draw_rect(button_x, button_y, button_w, button_h, GAME_OVER_BUTTON_BORDER_COLOR_BGRA, GAME_OVER_BUTTON_BORDER_THICKNESS)
    _draw_centered_text(
        canvas, GAME_OVER_BUTTON_TEXT, button_x + button_w // 2, button_y + button_h // 2,
        GAME_OVER_BUTTON_FONT_SIZE, GAME_OVER_TEXT_COLOR_BGRA, GAME_OVER_BUTTON_TEXT_THICKNESS,
    )

    _draw_centered_text(
        canvas, GAME_OVER_HINT_TEXT, center_x, band_y + GAME_OVER_HINT_OFFSET_Y,
        GAME_OVER_HINT_FONT_SIZE, GAME_OVER_TEXT_COLOR_BGRA, GAME_OVER_HINT_THICKNESS,
    )


def _cell_pixel_pos(position: Position, cell_size: int) -> Tuple[int, int]:
    """Converts a board cell to its pixel position on the canvas,
    including the side panel's width - one place for that offset so
    drawing and click mapping can't drift out of sync."""
    x, y = BoardView.cell_to_pixel(position, cell_size)
    return x + side_panel_width_for(cell_size), y


def _draw_centered_text(canvas: Img, text: str, center_x: int, center_y: int, font_size: float, color_bgra, thickness: int) -> None:
    width, height = canvas.text_size(text, font_size, thickness)
    x = center_x - width // 2
    y = center_y + height // 2
    canvas.put_text(text, x, y, font_size, color_bgra, thickness)


def _square_name(position: Position, board_height: int) -> str:
    file_letter = chr(ord("a") + position.col)
    rank_number = board_height - position.row
    return f"{file_letter}{rank_number}"


def _format_elapsed(elapsed_ms: int) -> str:
    total_seconds = elapsed_ms // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


_ALGEBRAIC_LETTER_BY_KIND = {KING: "K", QUEEN: "Q", ROOK: "R", BISHOP: "B", KNIGHT: "N"}  # pawn has no letter


def _move_notation(entry: MoveLogEntry, board_height: int) -> str:
    """Formats a move log entry as algebraic-style notation, e.g.
    "e2-e4", "Ng1-f3", "Qd1xh5". Keeps the source square, unlike
    standard chess notation, since several pieces can move at once here."""
    source = _square_name(entry.from_pos, board_height)
    dest = _square_name(entry.to_pos, board_height)
    letter = _ALGEBRAIC_LETTER_BY_KIND.get(entry.kind, "")
    separator = "x" if entry.is_capture else "-"
    return f"{letter}{source}{separator}{dest}"


def _draw_side_panel(
    canvas: Img,
    x: int,
    panel_height: int,
    team_label: str,
    score: int,
    entries: Tuple[MoveLogEntry, ...],
    board_height: int,
    cell_size: int,
) -> None:
    panel_width = side_panel_width_for(cell_size)
    _blend_solid_rect(canvas, x, 0, panel_width, panel_height, SIDE_PANEL_BACKGROUND_COLOR_BGRA)

    center_x = x + panel_width // 2
    _draw_centered_text(
        canvas, team_label, center_x, SIDE_PANEL_TEAM_LABEL_Y,
        SIDE_PANEL_HEADER_FONT_SIZE, SIDE_PANEL_TEXT_COLOR_BGRA, SIDE_PANEL_HEADER_THICKNESS,
    )
    _draw_centered_text(
        canvas, f"Score: {score}", center_x, SIDE_PANEL_SCORE_Y,
        SIDE_PANEL_HEADER_FONT_SIZE, SIDE_PANEL_ACCENT_COLOR_BGRA, SIDE_PANEL_HEADER_THICKNESS,
    )

    time_column_x = x + SIDE_PANEL_PADDING
    move_column_x = x + round(panel_width * SIDE_PANEL_MOVE_COLUMN_FRACTION)
    canvas.put_text("Time", time_column_x, SIDE_PANEL_COLUMNS_Y, SIDE_PANEL_ROW_FONT_SIZE, SIDE_PANEL_ACCENT_COLOR_BGRA, SIDE_PANEL_ROW_THICKNESS)
    canvas.put_text("Move", move_column_x, SIDE_PANEL_COLUMNS_Y, SIDE_PANEL_ROW_FONT_SIZE, SIDE_PANEL_ACCENT_COLOR_BGRA, SIDE_PANEL_ROW_THICKNESS)

    max_rows = max(0, (panel_height - SIDE_PANEL_ROWS_START_Y) // SIDE_PANEL_ROW_HEIGHT)
    for row_index, entry in enumerate(entries[-max_rows:] if max_rows else ()):
        row_y = SIDE_PANEL_ROWS_START_Y + row_index * SIDE_PANEL_ROW_HEIGHT
        move_text = _move_notation(entry, board_height)
        canvas.put_text(_format_elapsed(entry.elapsed_ms), time_column_x, row_y, SIDE_PANEL_ROW_FONT_SIZE, SIDE_PANEL_TEXT_COLOR_BGRA, SIDE_PANEL_ROW_THICKNESS)
        canvas.put_text(move_text, move_column_x, row_y, SIDE_PANEL_ROW_FONT_SIZE, SIDE_PANEL_TEXT_COLOR_BGRA, SIDE_PANEL_ROW_THICKNESS)


class Renderer:
    """Draws the board, pieces, highlights, and side panels from a
    BoardViewState. Pure rendering logic - it never touches input or
    opens a window, so it stays easy to unit test."""

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
        game_over_progress: float = 1.0,
    ) -> Img:
        side_panel_width = side_panel_width_for(cell_size)
        board_pixel_width = view_state.width * cell_size
        board_pixel_height = view_state.height * cell_size
        canvas_width = 2 * side_panel_width + board_pixel_width

        canvas = Img()
        canvas.img = np.full(
            (board_pixel_height, canvas_width, 4), SIDE_PANEL_BACKGROUND_COLOR_BGRA, dtype=np.uint8
        )
        board_background = self._board_view.new_canvas(view_state.width, view_state.height, cell_size)
        board_background.draw_on(canvas, side_panel_width, 0)

        for piece_view in view_state.pieces:
            if piece_view.target_position is not None and piece_view.progress is not None:
                x, y = BoardView.lerp_pixel(
                    piece_view.position, piece_view.target_position, piece_view.progress, cell_size
                )
                pixel_pos = (x + side_panel_width, y)
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
            _draw_game_over_overlay(canvas, view_state, cell_size, game_over_progress)

        _draw_side_panel(
            canvas, 0, board_pixel_height, "Black",
            view_state.scores.get(BLACK, 0), view_state.move_log.get(BLACK, ()), view_state.height, cell_size,
        )
        _draw_side_panel(
            canvas, side_panel_width + board_pixel_width, board_pixel_height, "White",
            view_state.scores.get(WHITE, 0), view_state.move_log.get(WHITE, ()), view_state.height, cell_size,
        )
        _blend_solid_rect(canvas, side_panel_width - SIDE_PANEL_DIVIDER_THICKNESS, 0, SIDE_PANEL_DIVIDER_THICKNESS, board_pixel_height, SIDE_PANEL_DIVIDER_COLOR_BGRA)
        _blend_solid_rect(canvas, side_panel_width + board_pixel_width, 0, SIDE_PANEL_DIVIDER_THICKNESS, board_pixel_height, SIDE_PANEL_DIVIDER_COLOR_BGRA)

        return canvas

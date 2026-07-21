from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

import cv2

from kungfu_chess.assets_config import DEFAULT_PIECE_SET
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.board_mapper import CELL_SIZE
from kungfu_chess.input.controller import Controller
from kungfu_chess.events.observers import MoveLogObserver, ScoreObserver
from kungfu_chess.view.renderer import Renderer, SIDE_PANEL_WIDTH, game_over_button_rect, side_panel_width_for


@dataclass
class GameSession:
    """Everything a single run of the game needs, bundled so build_game
    (see app.py) can hand it over in one piece - engine/controller as
    before, plus the observers that now hold data GameEngine/
    RealTimeArbiter themselves no longer do (see
    model.game_state.GameObserver)."""

    engine: GameEngine
    controller: Controller
    move_log: MoveLogObserver
    score: ScoreObserver

WINDOW_NAME = "Kung Fu Chess"
ESC_KEY = 27
RESTART_KEYS = (ord("r"), ord("R"))
TARGET_FRAME_MS = 16
PROCESS_PER_MONITOR_DPI_AWARE = 2

# compute_cell_size fits the board (plus both side panels, at their usual
# proportion to a square) within this fraction of the actual screen -
# leaves a visible margin instead of a window that touches every screen
# edge exactly.
_SCREEN_FIT_FRACTION = 0.9
_MIN_CELL_SIZE = 20


def _disable_windows_dpi_scaling() -> None:
    """Without this, when Windows Display Scaling isn't 100% (common on
    laptop screens), the window is drawn in full and then "stretched" by
    the OS onto more physical pixels than the image actually has - and
    the mouse coordinate returned from setMouseCallback no longer maps
    1:1 to a board pixel (BoardMapper assumes a 1:1 ratio). Must run
    *before* cv2.namedWindow."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _point_in_rect(x: int, y: int, rect: Tuple[int, int, int, int]) -> bool:
    rect_x, rect_y, width, height = rect
    return rect_x <= x < rect_x + width and rect_y <= y < rect_y + height


def _screen_resolution_px() -> Tuple[Optional[int], Optional[int]]:
    """Real screen resolution, Windows-only - same fallback style as
    _disable_windows_dpi_scaling: (None, None) whenever it can't be read
    (any other OS, or the OS call fails), so compute_cell_size falls back
    to the fixed default CELL_SIZE instead of crashing."""
    if sys.platform != "win32":
        return None, None
    import ctypes

    try:
        user32 = ctypes.windll.user32
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except (AttributeError, OSError):
        return None, None


def compute_cell_size(board_width: int, board_height: int, screen_size: Callable = _screen_resolution_px) -> int:
    """Picks a cell size that fits board_width x board_height squares,
    plus both side panels, within _SCREEN_FIT_FRACTION of the actual
    screen - decided once at startup (nothing here supports resizing
    mid-game), so the whole layout fits whatever screen is actually
    available instead of always being the fixed default CELL_SIZE.
    screen_size is injectable so tests can supply a fixed fake resolution
    instead of depending on the real display.

    Calls _disable_windows_dpi_scaling() itself, before querying the
    resolution - callers (see app.py) may run this before ever calling
    run(), and without DPI-awareness set first, Windows silently hands
    back the *scaled-down* resolution instead of the real one, on any
    machine with Display Scaling != 100% - producing a board sized as if
    the screen were smaller than it actually is."""
    _disable_windows_dpi_scaling()
    screen_width, screen_height = screen_size()
    if screen_width is None or screen_height is None:
        return CELL_SIZE

    panel_width_in_cells = SIDE_PANEL_WIDTH / CELL_SIZE
    height_limited = (screen_height * _SCREEN_FIT_FRACTION) / board_height
    width_limited = (screen_width * _SCREEN_FIT_FRACTION) / (board_width + 2 * panel_width_in_cells)

    return max(_MIN_CELL_SIZE, round(min(height_limited, width_limited)))


def run(
    build_game: Callable[[int], GameSession],
    cell_size: int = CELL_SIZE,
    piece_set: str = DEFAULT_PIECE_SET,
) -> None:
    """build_game(cell_size) is called once to start, and again every
    time the player restarts from the game-over screen - it must return a
    fresh GameSession each time (a new board, a new arbiter, fresh
    observers), not reset an existing one, since none of those types
    have a reset() method. It takes cell_size so it can size its
    BoardMapper's x_offset to match whatever this Renderer actually
    draws with (see compute_cell_size for how callers typically pick
    that cell_size) - a mismatch here would reproduce the old
    HUD_HEIGHT click-mapping gap. The Renderer is created once here (not
    global state) - its caches (animations/board background) stay alive
    across restarts too."""
    _disable_windows_dpi_scaling()
    cv2.namedWindow(WINDOW_NAME)

    current: Dict[str, GameSession] = {}

    def start_new_game() -> None:
        current["session"] = build_game(cell_size)

    def on_mouse(event: int, x: int, y: int, flags: int, param: object) -> None:
        session = current["session"]
        if event == cv2.EVENT_LBUTTONDOWN:
            if session.engine.is_game_over():
                view_state = session.engine.snapshot()
                button_rect = game_over_button_rect(view_state.width, view_state.height, cell_size)
                if _point_in_rect(x, y, button_rect):
                    start_new_game()
                return
            session.controller.handle_click(x, y)
        elif event == cv2.EVENT_RBUTTONDOWN:
            session.controller.handle_jump(x, y)

    start_new_game()
    cv2.setMouseCallback(WINDOW_NAME, on_mouse)
    frame_renderer = Renderer()
    last_time = time.perf_counter()

    try:
        while True:
            now = time.perf_counter()
            dt_ms = int((now - last_time) * 1000)
            last_time = now

            session = current["session"]
            engine = session.engine
            controller = session.controller

            engine.wait(dt_ms)
            view_state = engine.snapshot(move_log=session.move_log.as_dict(), scores=session.score.as_dict())
            selected = controller.selected_pos
            legal_destinations = engine.legal_destinations(selected) if selected is not None else None
            canvas = frame_renderer.draw(
                view_state, cell_size, piece_set, selected_position=selected, legal_destinations=legal_destinations,
                invalid_target=controller.invalid_target,
            )
            key = canvas.show(WINDOW_NAME, wait_ms=TARGET_FRAME_MS)

            window_closed = cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1
            if key == ESC_KEY or window_closed:
                break
            if engine.is_game_over() and key in RESTART_KEYS:
                start_new_game()
                last_time = time.perf_counter()
    finally:
        cv2.destroyAllWindows()

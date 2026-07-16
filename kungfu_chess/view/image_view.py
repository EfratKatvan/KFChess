from __future__ import annotations

import sys
import time

import cv2

from kungfu_chess.assets_config import DEFAULT_PIECE_SET
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.board_mapper import CELL_SIZE
from kungfu_chess.input.controller import Controller
from kungfu_chess.view.renderer import Renderer

WINDOW_NAME = "Kung Fu Chess"
ESC_KEY = 27
TARGET_FRAME_MS = 16
PROCESS_PER_MONITOR_DPI_AWARE = 2


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


def _on_mouse(event: int, x: int, y: int, controller: Controller) -> None:
    if event == cv2.EVENT_LBUTTONDOWN:
        controller.handle_click(x, y)
    elif event == cv2.EVENT_RBUTTONDOWN:
        controller.handle_jump(x, y)


def run(
    engine: GameEngine,
    controller: Controller,
    cell_size: int = CELL_SIZE,
    piece_set: str = DEFAULT_PIECE_SET,
) -> None:
    """The Renderer is created once here (not global state) - its caches
    (animations/board background) stay alive for the whole run."""
    _disable_windows_dpi_scaling()
    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, lambda event, x, y, flags, param: _on_mouse(event, x, y, controller))

    frame_renderer = Renderer()
    last_time = time.perf_counter()

    try:
        while True:
            now = time.perf_counter()
            dt_ms = int((now - last_time) * 1000)
            last_time = now

            engine.wait(dt_ms)
            view_state = engine.snapshot()
            selected = controller.selected_pos
            legal_destinations = engine.legal_destinations(selected) if selected is not None else None
            canvas = frame_renderer.draw(
                view_state, cell_size, piece_set, selected_position=selected, legal_destinations=legal_destinations,
                invalid_target=controller.invalid_target,
            )
            key = canvas.show(WINDOW_NAME, wait_ms=TARGET_FRAME_MS)

            window_closed = cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1
            if key == ESC_KEY or window_closed or engine.is_game_over():
                break
    finally:
        cv2.destroyAllWindows()

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


def _disable_windows_dpi_scaling() -> None:
    """בלי זה, אם ה-Display Scaling של Windows מוגדר לא 100% (למשל 125%/150% -
    נפוץ במסכי מחשב ניידים), חלון ה-GUI מצויר במלואו ואז "נמתח" ע"י מערכת
    ההפעלה על יותר פיקסלים פיזיים ממה שיש בתמונה עצמה - וקואורדינטת העכבר
    שחוזרת מ-setMouseCallback כבר לא תואמת 1:1 לפיקסל בלוח (BoardMapper
    מניח יחס 1:1). קריאה הזו ("Process DPI Awareness") אומרת לחלונות
    "אל תמתח, תן לי את הפיקסלים הפיזיים כמו שהם" - וזה חייב לרוץ *לפני*
    יצירת כל חלון (cv2.namedWindow)."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _on_mouse(event: int, x: int, y: int, controller: Controller) -> None:
    """קליק שמאלי מנותב ל-handle_click (בחירה/בקשת מהלך), קליק ימני
    ל-handle_jump (ההרחבה המותאמת אישית שמעבר ל-DSL הרשמי)."""
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
    """הלולאה האינטראקטיבית: בכל פריים מקדמת את הזמן לפי ה-dt שחלף בפועל
    (engine.wait), מרנדרת (Renderer.draw) ומציגה. רצה עד ESC, סגירת
    החלון, או סיום המשחק. piece_set בוחר בין חבילות הגרפיקה (ר'
    assets_config.PIECE_SETS). ה-Renderer נוצר פעם אחת כאן (לא global
    state) - הקאשים שלו (אנימציות/רקע-לוח) נשארים חיים לאורך כל ההרצה."""
    _disable_windows_dpi_scaling()
    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, lambda event, x, y, flags, param: _on_mouse(event, x, y, controller))

    frame_renderer = Renderer()
    total_elapsed_ms = 0
    last_time = time.perf_counter()

    try:
        while True:
            now = time.perf_counter()
            dt_ms = int((now - last_time) * 1000)
            last_time = now
            total_elapsed_ms += dt_ms

            engine.wait(dt_ms)
            snapshot = engine.snapshot()
            canvas = frame_renderer.draw(snapshot, total_elapsed_ms, cell_size, piece_set)
            key = canvas.show(WINDOW_NAME, wait_ms=TARGET_FRAME_MS)

            window_closed = cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1
            if key == ESC_KEY or window_closed or engine.is_game_over():
                break
    finally:
        cv2.destroyAllWindows()

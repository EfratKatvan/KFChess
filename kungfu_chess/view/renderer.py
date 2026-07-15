from __future__ import annotations

from typing import Optional

import numpy as np

from kungfu_chess.assets_config import DEFAULT_PIECE_SET, asset_code
from kungfu_chess.engine.board_view_state import BoardViewState
from kungfu_chess.input.board_mapper import CELL_SIZE
from kungfu_chess.view.animation import AnimationCache, frame_index
from kungfu_chess.view.board_view import BoardView
from kungfu_chess.view.img import Img

# תכלת-קרח שקופה-למחצה (BGRA) - "שעון החול" שמצטייר מעל כלי קפוא בקירור.
COOLDOWN_OVERLAY_COLOR_BGRA = (235, 206, 135, 120)


def _draw_cooldown_overlay(canvas: Img, pixel_pos: tuple, remaining_fraction: float, cell_size: int) -> None:
    """"שעון חול": הצפה תכלת שקופה-למחצה שמכסה חלק מהתא היורד עם הזמן -
    מלא כשהקירור מתחיל, ונעלם לגמרי (הכלי "משתחרר") כשהוא מסתיים. ה"חול"
    מתרוקן מלמעלה - הקצה העליון של ההצפה יורד עם הזמן, וה"חול" שנשאר
    נשקע כלפי מטה עד שהוא נעלם."""
    if remaining_fraction <= 0:
        return
    overlay_height = max(1, round(cell_size * remaining_fraction))
    overlay = Img()
    overlay.img = np.full((overlay_height, cell_size, 4), COOLDOWN_OVERLAY_COLOR_BGRA, dtype=np.uint8)
    x, y = pixel_pos
    overlay.draw_on(canvas, x, y + (cell_size - overlay_height))


class Renderer:
    """מרכיבה רקע-לוח (BoardView) + פריים-אנימציה נכון לכל כלי
    (AnimationCache) לתוך Img אחד, לכל פריים - מ-BoardViewState בלבד
    (ה"לוח תצוגה" הנפרד מ-Board האמיתי, ר' engine/board_view_state.py).
    אין כאן שום ידיעה על Motion/Jump/Cooldown/Piece.state - כל ה-state
    הויזואלי כבר מגיע פתור מראש בכל PieceView. animation_cache ו-board_view
    מוזרקים (ולא state גלובלי ברמת המודול) כדי שכל צרכן - image_view
    בהרצה אמיתית, או טסט - יחזיק את הקאש שלו, בלי לדלוף בין הרצות."""

    def __init__(self, animation_cache: Optional[AnimationCache] = None, board_view: Optional[BoardView] = None) -> None:
        self._animation_cache = animation_cache if animation_cache is not None else AnimationCache()
        self._board_view = board_view if board_view is not None else BoardView()

    def draw(
        self,
        view_state: BoardViewState,
        cell_size: int = CELL_SIZE,
        piece_set: str = DEFAULT_PIECE_SET,
    ) -> Img:
        """מרנדרת פריים בודד: רקע הלוח + כל כלי בפריים/מיקום הנכונים לפי
        ה-visual_state הכבר-פתור שלו. לוגיקה טהורה - לא פותחת חלון ולא
        נוגעת בקלט, כדי שתהיה ניתנת לבדיקה ביחידה. piece_set בוחר בין
        pieces1/pieces2 (ר' assets_config.PIECE_SETS)."""
        canvas = self._board_view.new_canvas(view_state.width, view_state.height, cell_size)

        for piece_view in view_state.pieces:
            if piece_view.target_position is not None and piece_view.progress is not None:
                pixel_pos = BoardView.lerp_pixel(
                    piece_view.position, piece_view.target_position, piece_view.progress, cell_size
                )
            else:
                pixel_pos = BoardView.cell_to_pixel(piece_view.position, cell_size)

            code = asset_code(piece_view.color, piece_view.kind)
            animation = self._animation_cache.load(code, piece_view.visual_state, cell_size, piece_set)
            frame = animation.frames[frame_index(piece_view.elapsed_ms, animation)]
            frame.draw_on(canvas, *pixel_pos)

            if piece_view.remaining_fraction is not None:
                _draw_cooldown_overlay(canvas, pixel_pos, piece_view.remaining_fraction, cell_size)

        return canvas

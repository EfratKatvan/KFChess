from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

from kungfu_chess.assets_config import DEFAULT_PIECE_SET, asset_code
from kungfu_chess.input.board_mapper import CELL_SIZE
from kungfu_chess.model.game_snapshot import GameSnapshot
from kungfu_chess.model.piece import IDLE as IDLE_STATE
from kungfu_chess.model.piece import Piece
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.motion import LONG_REST, SHORT_REST, motion_duration_ms
from kungfu_chess.realtime.real_time_arbiter import (
    COOLDOWN_DURATION_MS,
    JUMP_DURATION_MS,
    SHORT_REST_DURATION_MS,
)
from kungfu_chess.view.animation import AnimationCache, frame_index
from kungfu_chess.view.board_view import BoardView
from kungfu_chess.view.img import Img

MOVE_STATE = "move"
JUMP_STATE = "jump"

# תכלת-קרח שקופה-למחצה (BGRA) - "שעון החול" שמצטייר מעל כלי קפוא בקירור.
COOLDOWN_OVERLAY_COLOR_BGRA = (235, 206, 135, 120)


def resolve_visual_state(
    piece: Piece, snapshot: GameSnapshot, total_elapsed_ms: int, cell_size: int
) -> Tuple[str, int, Tuple[int, int]]:
    """מחזירה (state, elapsed_ms_in_state, pixel_position) לכלי נתון, לפי
    חיפוש ב-motions/jumps/cooldowns של ה-snapshot. סדר הבדיקה תואם לכך
    שכלי לא יכול להיות בו-זמנית בקפיצה ובתנועה (RealTimeArbiter חוסם את
    זה) - אז אין דו-משמעות איזה state "מנצח"."""
    for jump in snapshot.jumps:
        if jump.position == piece.cell:
            elapsed_ms = JUMP_DURATION_MS - jump.remaining_ms
            return JUMP_STATE, elapsed_ms, BoardView.cell_to_pixel(piece.cell, cell_size)

    for motion in snapshot.motions:
        if motion.piece.id == piece.id:
            duration = motion_duration_ms(piece.cell, motion.to_pos)
            elapsed_ms = duration - motion.remaining_ms
            progress = elapsed_ms / duration if duration > 0 else 1.0
            pixel_pos = BoardView.lerp_pixel(piece.cell, motion.to_pos, progress, cell_size)
            return MOVE_STATE, elapsed_ms, pixel_pos

    for cooldown in snapshot.cooldowns:
        if cooldown.position == piece.cell:
            full_duration = SHORT_REST_DURATION_MS if cooldown.kind == SHORT_REST else COOLDOWN_DURATION_MS
            elapsed_ms = full_duration - cooldown.remaining_ms
            return cooldown.kind, elapsed_ms, BoardView.cell_to_pixel(piece.cell, cell_size)

    return IDLE_STATE, total_elapsed_ms, BoardView.cell_to_pixel(piece.cell, cell_size)


def cooldown_remaining_fraction(state: str, elapsed_ms: int) -> float:
    """1.0 ברגע שהקירור מתחיל, יורד ל-0.0 ברגע שהוא נגמר - זה "שעון החול":
    הכמות שממנה נגזר גובה ההצפה שמכסה את התא. state שאינו short_rest/
    long_rest לא רלוונטי כאן (הקריאה למעלה כבר מוודאת את זה)."""
    full_duration = SHORT_REST_DURATION_MS if state == SHORT_REST else COOLDOWN_DURATION_MS
    remaining_ms = full_duration - elapsed_ms
    return max(0.0, min(1.0, remaining_ms / full_duration))


def _draw_cooldown_overlay(canvas: Img, pixel_pos: Tuple[int, int], remaining_fraction: float, cell_size: int) -> None:
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
    (AnimationCache) לתוך Img אחד, לכל פריים. animation_cache ו-board_view
    מוזרקים (ולא state גלובלי ברמת המודול) כדי שכל צרכן - image_view
    בהרצה אמיתית, או טסט - יחזיק את הקאש שלו, בלי לדלוף בין הרצות."""

    def __init__(self, animation_cache: Optional[AnimationCache] = None, board_view: Optional[BoardView] = None) -> None:
        self._animation_cache = animation_cache if animation_cache is not None else AnimationCache()
        self._board_view = board_view if board_view is not None else BoardView()

    def draw(
        self,
        snapshot: GameSnapshot,
        total_elapsed_ms: int,
        cell_size: int = CELL_SIZE,
        piece_set: str = DEFAULT_PIECE_SET,
    ) -> Img:
        """מרנדרת פריים בודד: רקע הלוח + כל כלי בפריים/מיקום הנכונים לפי
        ה-state הפעיל שלו (idle/move/jump/short_rest/long_rest). לוגיקה
        טהורה - לא פותחת חלון ולא נוגעת בקלט, כדי שתהיה ניתנת לבדיקה
        ביחידה. piece_set בוחר בין pieces1/pieces2 (ר' PIECE_SETS)."""
        board = snapshot.board
        canvas = self._board_view.new_canvas(board.width, board.height, cell_size)

        for row in range(board.height):
            for col in range(board.width):
                piece = board.piece_at(Position(row, col))
                if piece is None:
                    continue

                state, elapsed_ms, pixel_pos = resolve_visual_state(piece, snapshot, total_elapsed_ms, cell_size)
                animation = self._animation_cache.load(asset_code(piece), state, cell_size, piece_set)
                frame = animation.frames[frame_index(elapsed_ms, animation)]
                frame.draw_on(canvas, *pixel_pos)

                if state in (SHORT_REST, LONG_REST):
                    remaining_fraction = cooldown_remaining_fraction(state, elapsed_ms)
                    _draw_cooldown_overlay(canvas, pixel_pos, remaining_fraction, cell_size)

        return canvas

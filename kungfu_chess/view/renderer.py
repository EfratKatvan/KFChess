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

# תכלת-קרח שקופה-למחצה (BGRA) - "שעון החול" שמצטייר מעל כלי קפוא בקירור.
COOLDOWN_OVERLAY_COLOR_BGRA = (235, 206, 135, 120)

# מסגרת זהובה - מדגישה את התא שנבחר כרגע (Controller.selected_pos).
SELECTION_HIGHLIGHT_COLOR_BGRA = (0, 215, 255, 255)
SELECTION_HIGHLIGHT_THICKNESS = 4

# ירוק שקוף-למחצה - צובע את כל התא-יעד האפשרי לכלי הנבחר (RuleEngine.legal_destinations).
DESTINATION_HIGHLIGHT_COLOR_BGRA = (60, 200, 60, 130)

# רצועת HUD מעל ומתחת ללוח - ניקוד לכל צבע (BoardViewState.scores). לא חלק
# מהלוח עצמו (BoardView) בכוונה - זו תוספת של ה-Renderer, לא של "איך נראה
# הלוח".
HUD_HEIGHT = 60
HUD_BACKGROUND_COLOR_BGRA = (40, 40, 40, 255)
HUD_TEXT_COLOR_BGRA = (255, 255, 255, 255)
HUD_FONT_SIZE = 1.0


def _blend_solid_rect(canvas: Img, x: int, y: int, width: int, height: int, color_bgra) -> None:
    """מבליטה (עם alpha blending אמיתי, ר' Img.draw_on) מלבן בצבע-אחיד על
    הקנבס - הבסיס המשותף לשעון-החול ולצביעת יעדים אפשריים."""
    overlay = Img()
    overlay.img = np.full((height, width, 4), color_bgra, dtype=np.uint8)
    overlay.draw_on(canvas, x, y)


def _draw_cooldown_overlay(canvas: Img, pixel_pos: Tuple[int, int], remaining_fraction: float, cell_size: int) -> None:
    """"שעון חול": הצפה תכלת שקופה-למחצה שמכסה חלק מהתא היורד עם הזמן -
    מלא כשהקירור מתחיל, ונעלם לגמרי (הכלי "משתחרר") כשהוא מסתיים. ה"חול"
    מתרוקן מלמעלה - הקצה העליון של ההצפה יורד עם הזמן, וה"חול" שנשאר
    נשקע כלפי מטה עד שהוא נעלם."""
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


def _draw_score_hud(canvas: Img, scores: Dict[str, int], board_pixel_height: int) -> None:
    """"Black: X" ברצועה העליונה, "White: Y" ברצועה התחתונה - מחוץ ללוח
    עצמו לגמרי, לא מצטייר מעל אף כלי."""
    canvas.put_text(f"Black: {scores.get(BLACK, 0)}", 10, HUD_HEIGHT // 2 + 8, HUD_FONT_SIZE, HUD_TEXT_COLOR_BGRA)
    canvas.put_text(
        f"White: {scores.get(WHITE, 0)}", 10, HUD_HEIGHT + board_pixel_height + HUD_HEIGHT // 2 + 8,
        HUD_FONT_SIZE, HUD_TEXT_COLOR_BGRA,
    )


class Renderer:
    """מרכיבה רקע-לוח (BoardView) + פריים-אנימציה נכון לכל כלי
    (AnimationCache) + רצועת-ניקוד (HUD) לתוך Img אחד, לכל פריים -
    מ-BoardViewState בלבד (ה"לוח תצוגה" הנפרד מ-Board האמיתי, ר'
    engine/board_view_state.py). אין כאן שום ידיעה על Motion/Jump/Cooldown/
    Piece.state - כל ה-state הויזואלי כבר מגיע פתור מראש בכל PieceView.
    animation_cache ו-board_view מוזרקים (ולא state גלובלי ברמת המודול)
    כדי שכל צרכן - image_view בהרצה אמיתית, או טסט - יחזיק את הקאש שלו,
    בלי לדלוף בין הרצות."""

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
        """מרנדרת פריים בודד: רצועת-ניקוד עליונה + הלוח (עם כל כלי בפריים/
        מיקום הנכונים לפי ה-visual_state הכבר-פתור שלו) + רצועת-ניקוד
        תחתונה. לוגיקה טהורה - לא פותחת חלון ולא נוגעת בקלט, כדי שתהיה
        ניתנת לבדיקה ביחידה. piece_set בוחר בין pieces1/pieces2 (ר'
        assets_config.PIECE_SETS). selected_position/legal_destinations -
        לא חלק מ-BoardViewState (אלה בחירות/שאילתות בצד ה-view/קלט, לא
        state של המשחק עצמו): selected_position מצייר מסגרת הדגשה על התא
        הנבחר (Controller.selected_pos), legal_destinations צובע (שקוף-
        למחצה) כל יעד אפשרי (GameEngine.legal_destinations)."""
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
            else:
                x, y = BoardView.cell_to_pixel(piece_view.position, cell_size)
            pixel_pos = (x, y + HUD_HEIGHT)

            code = asset_code(piece_view.color, piece_view.kind)
            animation = self._animation_cache.load(code, piece_view.visual_state, cell_size, piece_set)
            frame = animation.frames[frame_index(piece_view.elapsed_ms, animation)]
            frame.draw_on(canvas, *pixel_pos)

            if piece_view.remaining_fraction is not None:
                _draw_cooldown_overlay(canvas, pixel_pos, piece_view.remaining_fraction, cell_size)

        if selected_position is not None:
            x, y = BoardView.cell_to_pixel(selected_position, cell_size)
            _draw_selection_highlight(canvas, (x, y + HUD_HEIGHT), cell_size)

        if legal_destinations is not None:
            for destination in legal_destinations:
                x, y = BoardView.cell_to_pixel(destination, cell_size)
                _draw_destination_highlight(canvas, (x, y + HUD_HEIGHT), cell_size)

        _draw_score_hud(canvas, view_state.scores, board_pixel_height)

        return canvas

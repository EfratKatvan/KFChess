from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from kungfu_chess.input.board_mapper import CELL_SIZE
from kungfu_chess.io.board_parser import piece_to_token
from kungfu_chess.model.game_snapshot import GameSnapshot
from kungfu_chess.model.piece import IDLE as IDLE_STATE
from kungfu_chess.model.piece import Piece
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.motion import SHORT_REST, motion_duration_ms
from kungfu_chess.realtime.real_time_arbiter import (
    COOLDOWN_DURATION_MS,
    JUMP_DURATION_MS,
    SHORT_REST_DURATION_MS,
)
from kungfu_chess.view.img import Img

MOVE_STATE = "move"
JUMP_STATE = "jump"

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
BOARD_IMAGE_PATH = ASSETS_DIR / "board.png"

# pieces1 הם נכסי-פיתוח (placeholder) - בלי alpha אמיתי, עם תווית state+frame
# צרובה בתוך כל תמונה. pieces2 הם אמנות סופית עם ערוץ alpha אמיתי. שתיהן
# מ-CTD26 בלבד - ברירת המחדל היא pieces2, אבל אפשר להחליף חופשית.
PIECE_SETS = ("pieces1", "pieces2")
DEFAULT_PIECE_SET = "pieces2"


class MissingAssetError(Exception):
    """נזרקת כשלא נמצאו נכסי אנימציה (config.json או תמונות sprites) עבור
    כלי/state/piece_set נתונים תחת kungfu_chess/assets - למשל בעקבות קוד
    כלי שגוי, piece_set לא מוכר, או תיקייה חסרה - במקום FileNotFoundError
    גנרי שלא אומר במפורש מה בדיוק חסר."""


def _pieces_dir(piece_set: str) -> Path:
    if piece_set not in PIECE_SETS:
        raise MissingAssetError(f"unknown piece set '{piece_set}' (expected one of {PIECE_SETS})")
    return ASSETS_DIR / piece_set


def asset_code(piece: Piece) -> str:
    """הטוקן של הפרויקט הוא <color><KIND> (למשל "wP"), וב-CTD26 זה הפוך:
    <KIND><COLOR> (למשל "PW")."""
    token = piece_to_token(piece)
    color_letter, kind_letter = token[0], token[1]
    return f"{kind_letter}{color_letter.upper()}"


def _cell_to_pixel(position: Position, cell_size: int) -> Tuple[int, int]:
    return position.col * cell_size, position.row * cell_size


def _lerp_pixel(source: Position, destination: Position, progress: float, cell_size: int) -> Tuple[int, int]:
    sx, sy = _cell_to_pixel(source, cell_size)
    dx, dy = _cell_to_pixel(destination, cell_size)
    return int(sx + (dx - sx) * progress), int(sy + (dy - sy) * progress)


@dataclass
class StateAnimation:
    frames: List[Img]
    frames_per_sec: float
    is_loop: bool


_animation_cache: Dict[Tuple[str, str, str, int], StateAnimation] = {}
_board_background_cache: Dict[Tuple[int, int, int], Img] = {}


def _load_state_animation(
    asset_code: str, state: str, cell_size: int, piece_set: str = DEFAULT_PIECE_SET
) -> StateAnimation:
    key = (piece_set, asset_code, state, cell_size)
    cached = _animation_cache.get(key)
    if cached is not None:
        return cached

    state_dir = _pieces_dir(piece_set) / asset_code / "states" / state
    config_path = state_dir / "config.json"
    if not config_path.is_file():
        raise MissingAssetError(
            f"no animation assets for piece '{asset_code}' state '{state}' in '{piece_set}' (expected {config_path})"
        )

    with open(config_path, encoding="utf-8") as config_file:
        config = json.load(config_file)

    sprite_paths = sorted((state_dir / "sprites").glob("*.png"), key=lambda p: int(p.stem))
    if not sprite_paths:
        raise MissingAssetError(
            f"no sprite frames for piece '{asset_code}' state '{state}' in '{piece_set}' "
            f"(expected under {state_dir / 'sprites'})"
        )

    frames = []
    for path in sprite_paths:
        # strip_background הוא no-op על תמונות שכבר עם alpha אמיתי (pieces2) -
        # ורק מסיר בפועל רקע אחיד מ-pieces1 שאין להן ערוץ שקיפות.
        frame = Img().read(path, size=(cell_size, cell_size), keep_aspect=True)
        frame.strip_background()
        frames.append(frame)

    animation = StateAnimation(
        frames=frames,
        frames_per_sec=config["graphics"]["frames_per_sec"],
        is_loop=config["graphics"]["is_loop"],
    )
    _animation_cache[key] = animation
    return animation


def frame_index(elapsed_ms: int, animation: StateAnimation) -> int:
    if not animation.frames:
        return 0
    raw_index = int(elapsed_ms / 1000 * animation.frames_per_sec)
    if animation.is_loop:
        return raw_index % len(animation.frames)
    return min(raw_index, len(animation.frames) - 1)


def _board_background(board_width: int, board_height: int, cell_size: int) -> Img:
    key = (board_width, board_height, cell_size)
    cached = _board_background_cache.get(key)
    if cached is not None:
        return cached

    background = Img().read(BOARD_IMAGE_PATH, size=(board_width * cell_size, board_height * cell_size))
    _board_background_cache[key] = background
    return background


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
            return JUMP_STATE, elapsed_ms, _cell_to_pixel(piece.cell, cell_size)

    for motion in snapshot.motions:
        if motion.piece.id == piece.id:
            duration = motion_duration_ms(piece.cell, motion.to_pos)
            elapsed_ms = duration - motion.remaining_ms
            progress = elapsed_ms / duration if duration > 0 else 1.0
            pixel_pos = _lerp_pixel(piece.cell, motion.to_pos, progress, cell_size)
            return MOVE_STATE, elapsed_ms, pixel_pos

    for cooldown in snapshot.cooldowns:
        if cooldown.position == piece.cell:
            full_duration = SHORT_REST_DURATION_MS if cooldown.kind == SHORT_REST else COOLDOWN_DURATION_MS
            elapsed_ms = full_duration - cooldown.remaining_ms
            return cooldown.kind, elapsed_ms, _cell_to_pixel(piece.cell, cell_size)

    return IDLE_STATE, total_elapsed_ms, _cell_to_pixel(piece.cell, cell_size)


def draw(
    snapshot: GameSnapshot,
    total_elapsed_ms: int,
    cell_size: int = CELL_SIZE,
    piece_set: str = DEFAULT_PIECE_SET,
) -> Img:
    """מרנדרת פריים בודד: רקע הלוח + כל כלי בפריים/מיקום הנכונים לפי
    ה-state הפעיל שלו (idle/move/jump/short_rest/long_rest). לוגיקה טהורה -
    לא פותחת חלון ולא נוגעת בקלט, כדי שתהיה ניתנת לבדיקה ביחידה. piece_set
    בוחר בין pieces1/pieces2 (ר' PIECE_SETS)."""
    board = snapshot.board
    canvas = Img()
    canvas.img = _board_background(board.width, board.height, cell_size).img.copy()

    for row in range(board.height):
        for col in range(board.width):
            piece = board.piece_at(Position(row, col))
            if piece is None:
                continue

            state, elapsed_ms, pixel_pos = resolve_visual_state(piece, snapshot, total_elapsed_ms, cell_size)
            animation = _load_state_animation(asset_code(piece), state, cell_size, piece_set)
            frame = animation.frames[frame_index(elapsed_ms, animation)]
            frame.draw_on(canvas, *pixel_pos)

    return canvas

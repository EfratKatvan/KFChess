from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from kungfu_chess.io.board_parser import piece_to_token
from kungfu_chess.model.piece import Piece

"""קורא-נכסים משותף ל-view וגם ל-realtime - שתי השכבות צריכות מידע מאותם
קבצי config.json של CTD26 (view: graphics.frames_per_sec/is_loop לרינדור,
realtime: physics.speed_m_per_sec/next_state_when_finished ללוגיקת המשחק
עצמה - ר' realtime/motion.py). הקובץ הזה לא שייך לאף אחת מהשכבות - הוא
פשוט יודע לקרוא נכס לפי (piece_set, asset_code, state)."""

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# pieces1 הם נכסי-פיתוח (placeholder) - בלי alpha אמיתי, עם תווית state+frame
# צרובה בתוך כל תמונה. pieces2 הם אמנות סופית עם ערוץ alpha אמיתי. שתיהן
# מ-CTD26 בלבד - ברירת המחדל היא pieces2, אבל אפשר להחליף חופשית.
PIECE_SETS = ("pieces1", "pieces2")
DEFAULT_PIECE_SET = "pieces2"


class MissingAssetError(Exception):
    """נזרקת כשלא נמצאו נכסים (config.json או תמונות sprites) עבור
    כלי/state/piece_set נתונים תחת kungfu_chess/assets - למשל בעקבות קוד
    כלי שגוי, piece_set לא מוכר, או תיקייה חסרה - במקום FileNotFoundError
    גנרי שלא אומר במפורש מה בדיוק חסר."""


def pieces_dir(piece_set: str) -> Path:
    if piece_set not in PIECE_SETS:
        raise MissingAssetError(f"unknown piece set '{piece_set}' (expected one of {PIECE_SETS})")
    return ASSETS_DIR / piece_set


def asset_code(piece: Piece) -> str:
    """הטוקן של הפרויקט הוא <color><KIND> (למשל "wP"), וב-CTD26 זה הפוך:
    <KIND><COLOR> (למשל "PW")."""
    token = piece_to_token(piece)
    color_letter, kind_letter = token[0], token[1]
    return f"{kind_letter}{color_letter.upper()}"


def _state_dir(asset_code: str, state: str, piece_set: str) -> Path:
    return pieces_dir(piece_set) / asset_code / "states" / state


def load_state_config(asset_code: str, state: str, piece_set: str = DEFAULT_PIECE_SET) -> Dict[str, Any]:
    """קוראת ומפרסרת את config.json בפועל, בזמן ריצה - הן physics
    (speed_m_per_sec, next_state_when_finished) והן graphics (frames_per_sec,
    is_loop)."""
    config_path = _state_dir(asset_code, state, piece_set) / "config.json"
    if not config_path.is_file():
        raise MissingAssetError(
            f"no config for piece '{asset_code}' state '{state}' in '{piece_set}' (expected {config_path})"
        )
    with open(config_path, encoding="utf-8") as config_file:
        return json.load(config_file)


def state_sprite_paths(asset_code: str, state: str, piece_set: str = DEFAULT_PIECE_SET) -> List[Path]:
    paths = sorted((_state_dir(asset_code, state, piece_set) / "sprites").glob("*.png"), key=lambda p: int(p.stem))
    if not paths:
        raise MissingAssetError(
            f"no sprite frames for piece '{asset_code}' state '{state}' in '{piece_set}' "
            f"(expected under {_state_dir(asset_code, state, piece_set) / 'sprites'})"
        )
    return paths

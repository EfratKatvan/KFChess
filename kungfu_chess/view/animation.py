from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from kungfu_chess.assets_config import DEFAULT_PIECE_SET, load_state_config, state_sprite_paths
from kungfu_chess.view.img import Img


@dataclass
class StateAnimation:
    frames: List[Img]
    frames_per_sec: float
    is_loop: bool


def frame_index(elapsed_ms: int, animation: StateAnimation) -> int:
    if not animation.frames:
        return 0
    raw_index = int(elapsed_ms / 1000 * animation.frames_per_sec)
    if animation.is_loop:
        return raw_index % len(animation.frames)
    return min(raw_index, len(animation.frames) - 1)


class AnimationCache:
    """טוענת (עם קאש) את הפריימים+config של כל (piece_set, קוד-כלי, state,
    cell_size). מוזרקת מבחוץ במקום global state ברמת המודול - כדי שכל
    צרכן (image_view בהרצה אמיתית, טסטים) יחזיק מופע משלו, בלי לדלוף
    מצב בין הרצות/טסטים."""

    def __init__(self) -> None:
        self._animations: Dict[Tuple[str, str, str, int], StateAnimation] = {}

    def load(self, asset_code: str, state: str, cell_size: int, piece_set: str = DEFAULT_PIECE_SET) -> StateAnimation:
        key = (piece_set, asset_code, state, cell_size)
        cached = self._animations.get(key)
        if cached is not None:
            return cached

        config = load_state_config(asset_code, state, piece_set)
        sprite_paths = state_sprite_paths(asset_code, state, piece_set)

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
        self._animations[key] = animation
        return animation

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
    """Loads (with caching) the frames+config for every (piece_set,
    piece-code, state, cell_size). Injected from outside instead of
    module-level global state - so every consumer (image_view in a real
    run, tests) holds its own instance, with no state leaking between
    runs/tests."""

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
            # strip_background is a no-op on images that already have real
            # alpha (pieces2) - it only actually strips a solid background
            # from pieces1, which have no transparency channel.
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

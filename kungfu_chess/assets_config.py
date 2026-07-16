from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from kungfu_chess.io.board_parser import color_kind_to_token

"""A shared asset reader for both view and realtime - both layers need
information from the same CTD26 config.json files (view:
graphics.frames_per_sec/is_loop for rendering, realtime:
physics.speed_m_per_sec/next_state_when_finished for the game logic
itself - see realtime/motion.py). This file doesn't belong to either
layer - it simply knows how to read an asset by
(piece_set, asset_code, state)."""

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# pieces1 are development (placeholder) assets - no real alpha, with a
# state+frame label baked into every image. pieces2 are the final art
# with a real alpha channel. Both are from CTD26 only - the default is
# pieces2, but it can be freely swapped.
PIECE_SETS = ("pieces1", "pieces2")
DEFAULT_PIECE_SET = "pieces2"


class MissingAssetError(Exception):
    """Raised when no assets (config.json or sprite images) are found
    for a given piece/state/piece_set under kungfu_chess/assets - e.g.
    due to a wrong piece code, an unknown piece_set, or a missing
    directory - instead of a generic FileNotFoundError that doesn't
    explicitly say what's missing."""


def pieces_dir(piece_set: str) -> Path:
    if piece_set not in PIECE_SETS:
        raise MissingAssetError(f"unknown piece set '{piece_set}' (expected one of {PIECE_SETS})")
    return ASSETS_DIR / piece_set


def asset_code(color: str, kind: str) -> str:
    """This project's token is <color><KIND> (e.g. "wP"), while in CTD26
    it's reversed: <KIND><COLOR> (e.g. "PW"). Takes raw color/kind
    (not a full Piece) - because PieceView (see
    engine/board_view_state.py) needs to call this too."""
    token = color_kind_to_token(color, kind)
    color_letter, kind_letter = token[0], token[1]
    return f"{kind_letter}{color_letter.upper()}"


def _state_dir(asset_code: str, state: str, piece_set: str) -> Path:
    return pieces_dir(piece_set) / asset_code / "states" / state


def load_state_config(asset_code: str, state: str, piece_set: str = DEFAULT_PIECE_SET) -> Dict[str, Any]:
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

from __future__ import annotations

import logging
import pathlib
import sys
from typing import Dict, FrozenSet, Optional

from kungfu_chess.client.client_state import CAPTURE_EVENT, GAME_OVER_EVENT, GAME_START_EVENT, MOVE_EVENT

"""Reactive sound effects: turns the event tags client_state.events_since
computes into short sounds. Windows-only (winsound is stdlib there) - a
no-op everywhere else, the same fallback style as view/image_view.py's
DPI-awareness probing. network_transport.py is the only caller, right
after computing each message's events_since - see its docstring for why
this lives there and not in view/network_presentation.py.

Uses winsound.PlaySound(path, SND_ASYNC) on a short .wav file, not
winsound.Beep - PlaySound's async flag hands playback off to Windows
itself and returns immediately, with no thread of our own needed at
all. Beep is blocking and, on real hardware, unreliable when called
concurrently from multiple threads; this is real-time (not turn-based)
chess, so overlapping move/capture events are common, and spawning a
thread per beep could itself raise under a burst (RuntimeError: can't
start new thread) - something that must never take the connection down
over a missed sound effect. PlaySound sidesteps that whole class of
problem rather than working around it."""

logger = logging.getLogger(__name__)

_SOUNDS_DIR = pathlib.Path(__file__).resolve().parent.parent / "assets" / "sounds"

_FILENAME_BY_EVENT: Dict[str, str] = {
    MOVE_EVENT: "move.wav",
    CAPTURE_EVENT: "capture.wav",
    GAME_START_EVENT: "game_start.wav",
    GAME_OVER_EVENT: "game_over.wav",
}

if sys.platform == "win32":
    import winsound
else:
    winsound = None  # type: ignore[assignment]


def _path_for(event: str) -> Optional[pathlib.Path]:
    filename = _FILENAME_BY_EVENT.get(event)
    if filename is None:
        return None
    path = _SOUNDS_DIR / filename
    return path if path.is_file() else None


def play_events(events: FrozenSet[str]) -> None:
    """Best-effort: never raises, never blocks the caller (the network
    thread) - a missed sound is never worth losing the connection over."""
    if winsound is None:
        return
    for event in events:
        path = _path_for(event)
        if path is None:
            continue
        try:
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        except RuntimeError as error:
            logger.debug("winsound.PlaySound failed (%s) - continuing without sound", error)

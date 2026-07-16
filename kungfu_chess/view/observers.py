from __future__ import annotations

from typing import Dict, List, Tuple

from kungfu_chess.engine.board_view_state import MoveLogEntry
from kungfu_chess.model.game_state import GameObserver, MoveLoggedEvent
from kungfu_chess.model.piece import WHITE, BLACK


class MoveLogObserver(GameObserver):
    """Accumulates MoveLoggedEvents into per-color, display-ready
    entries. GameEngine.request_move fires the event and moves on - it
    never holds this data itself, and never imports this class (this
    module is the only place that knows a move log exists)."""

    def __init__(self) -> None:
        self._entries: Dict[str, List[MoveLogEntry]] = {WHITE: [], BLACK: []}

    def on_move_logged(self, event: MoveLoggedEvent) -> None:
        entry = MoveLogEntry(event.elapsed_ms, event.from_pos, event.to_pos, event.kind, event.is_capture)
        self._entries.setdefault(event.color, []).append(entry)

    def as_dict(self) -> Dict[str, Tuple[MoveLogEntry, ...]]:
        """Read by the render loop each frame (see image_view.py) and
        handed to GameEngine.snapshot() - a plain dict/tuple copy, not a
        reference into this observer's own mutable list."""
        return {color: tuple(entries) for color, entries in self._entries.items()}

from __future__ import annotations

from typing import Dict, List, Tuple

from kungfu_chess.engine.board_view_state import MoveLogEntry
from kungfu_chess.model.game_state import GameObserver, MoveLoggedEvent, PieceCapturedEvent
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


class ScoreObserver(GameObserver):
    """Accumulates PieceCapturedEvents into a running per-color score.
    RealTimeArbiter fires the event the instant a capture resolves and
    moves on - it never holds a running score itself, the same split as
    MoveLogObserver above but for captures instead of move requests."""

    def __init__(self) -> None:
        self._scores: Dict[str, int] = {WHITE: 0, BLACK: 0}

    def on_piece_captured(self, event: PieceCapturedEvent) -> None:
        self._scores[event.color] = self._scores.get(event.color, 0) + event.points

    def as_dict(self) -> Dict[str, int]:
        """A plain dict copy, not a reference into this observer's own
        mutable dict - same reasoning as MoveLogObserver.as_dict()."""
        return dict(self._scores)

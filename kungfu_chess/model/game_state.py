from __future__ import annotations
from dataclasses import dataclass

from kungfu_chess.model.board import BoardRepresentation
from kungfu_chess.model.position import Position


@dataclass
class GameState:
    """The currently-live game state: the board + whether the game is
    over.

    Knows nothing about time, active motions, input, drawing, or text
    parsing - those belong to other layers (RealTimeArbiter, Controller,
    Renderer, IO)."""

    board: BoardRepresentation
    game_over: bool = False


@dataclass(frozen=True)
class MoveLoggedEvent:
    """Everything a move-log observer needs about a single completed
    move request - fired by GameEngine.request_move once a motion
    actually starts. GameEngine builds this and hands it to whoever's
    listening; it doesn't store move history itself, and doesn't know
    or care what a listener does with it."""

    color: str
    from_pos: Position
    to_pos: Position
    kind: str
    is_capture: bool
    elapsed_ms: int


@dataclass(frozen=True)
class PieceCapturedEvent:
    """Fired by RealTimeArbiter the instant a capture resolves - a
    normal landing on an occupied cell, or a jumper swallowing an
    attacker mid-air. color is who gets the points; kind/points describe
    the piece that was destroyed. The arbiter doesn't keep a running
    score itself once this fires - see events/observers.py's
    ScoreObserver, the mirror of MoveLogObserver but for captures."""

    color: str
    kind: str
    points: int


class GameObserver:
    """Base class for anything that wants to react to game events
    without GameEngine/RealTimeArbiter needing to know it exists -
    register with GameEngine.add_observer, which forwards registration
    to both. Override only the methods you care about; the defaults do
    nothing, so a move-log-only observer doesn't need to implement
    events it has no interest in."""

    def on_move_logged(self, event: MoveLoggedEvent) -> None:
        pass

    def on_piece_captured(self, event: PieceCapturedEvent) -> None:
        pass

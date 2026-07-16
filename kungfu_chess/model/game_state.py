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


class GameObserver:
    """Base class for anything that wants to react to game events
    without GameEngine needing to know it exists - register with
    GameEngine.add_observer. Override only the methods you care about;
    the defaults do nothing, so a move-log-only observer doesn't need to
    implement events it has no interest in."""

    def on_move_logged(self, event: MoveLoggedEvent) -> None:
        pass

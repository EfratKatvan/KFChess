from __future__ import annotations
from dataclasses import dataclass

from kungfu_chess.model.board import BoardRepresentation


@dataclass
class GameState:
    """The currently-live game state: the board + whether the game is
    over.

    Knows nothing about time, active motions, input, drawing, or text
    parsing - those belong to other layers (RealTimeArbiter, Controller,
    Renderer, IO)."""

    board: BoardRepresentation
    game_over: bool = False

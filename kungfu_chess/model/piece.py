from __future__ import annotations
from dataclasses import dataclass

from kungfu_chess.model.position import Position

WHITE = "white"
BLACK = "black"

KING = "king"
QUEEN = "queen"
ROOK = "rook"
BISHOP = "bishop"
KNIGHT = "knight"
PAWN = "pawn"

IDLE = "idle"
MOVING = "moving"
CAPTURED = "captured"


@dataclass
class Piece:
    """A chess piece. id is a stable identity that never changes - what
    distinguishes a Piece from a string like "wR": two different white
    pieces are two different objects, even if their color/kind match."""

    id: str
    color: str
    kind: str
    cell: Position
    state: str = IDLE

from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol

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


class PieceRepresentation(Protocol):
    """The shape rules/engine/realtime actually need from a piece -
    color/kind/cell/state are all both read AND written somewhere in
    that code (rule_engine.py's LastRankPromotion writes .kind,
    real_time_arbiter.py writes .cell/.state), so this declares plain
    mutable attributes, not read-only properties. Piece (below)
    satisfies this shape structurally, without inheriting from it - so
    would any other class with the same attributes."""

    id: str
    color: str
    kind: str
    cell: Position
    state: str


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

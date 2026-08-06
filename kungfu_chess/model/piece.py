from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from kungfu_chess.model.position import Position


class Color(str, Enum):
    """(str, Enum), same pattern client/phases.py's Phase/RoomAction
    already use - a member IS its own string value (Color.WHITE ==
    "white" is True), so this serializes over the wire and compares
    against a plain string exactly like the raw str constants this
    replaces did, while closing the gap those left open: nothing
    stops piece.color = "purple" from type-checking with a bare str
    field, but it does with this."""

    WHITE = "white"
    BLACK = "black"


class PieceKind(str, Enum):
    KING = "king"
    QUEEN = "queen"
    ROOK = "rook"
    BISHOP = "bishop"
    KNIGHT = "knight"
    PAWN = "pawn"


class PieceState(str, Enum):
    IDLE = "idle"
    MOVING = "moving"
    CAPTURED = "captured"


# Every existing `from kungfu_chess.model.piece import WHITE, KING, ...`
# keeps working unchanged - these are now enum members, not raw
# strings, but every comparison in rules/engine/server (piece.color ==
# WHITE, occupant.kind == KING, ...) is unaffected either way, since a
# (str, Enum) member equals its own string value in both directions.
WHITE = Color.WHITE
BLACK = Color.BLACK

KING = PieceKind.KING
QUEEN = PieceKind.QUEEN
ROOK = PieceKind.ROOK
BISHOP = PieceKind.BISHOP
KNIGHT = PieceKind.KNIGHT
PAWN = PieceKind.PAWN

IDLE = PieceState.IDLE
MOVING = PieceState.MOVING
CAPTURED = PieceState.CAPTURED


class PieceRepresentation(Protocol):
    """The shape rules/engine/realtime actually need from a piece -
    color/kind/cell/state are all both read AND written somewhere in
    that code (rule_engine.py's LastRankPromotion writes .kind,
    real_time_arbiter.py writes .cell/.state), so this declares plain
    mutable attributes, not read-only properties. Piece (below)
    satisfies this shape structurally, without inheriting from it - so
    would any other class with the same attributes."""

    id: str
    color: Color
    kind: PieceKind
    cell: Position
    state: PieceState


@dataclass
class Piece:
    """A chess piece. id is a stable identity that never changes - what
    distinguishes a Piece from a string like "wR": two different white
    pieces are two different objects, even if their color/kind match."""

    id: str
    color: Color
    kind: PieceKind
    cell: Position
    state: PieceState = IDLE

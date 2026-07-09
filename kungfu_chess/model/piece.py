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
    """כלי שחמט. id הוא זהות קבועה שלא משתנה - זה מה שמבדיל בין Piece
    למחרוזת "wR": שני כלים לבנים שונים הם שני אובייקטים שונים, גם אם
    color/kind זהים ביניהם."""

    id: str
    color: str
    kind: str
    cell: Position
    state: str = IDLE

from __future__ import annotations
from typing import Dict, Optional

from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece


class CellOccupiedError(Exception):
    """נזרקת כשמנסים להוסיף כלי לתא שכבר תפוס ע"י כלי אחר."""


class Board:
    """אוסף הכלים החיים על הלוח - יודע רק מי נמצא איפה.
    לא יודע חוקי שחמט, פיקסלים, טקסט או תזמון."""

    def __init__(self, width: int, height: int) -> None:
        self._width = width
        self._height = height
        self._pieces: Dict[Position, Piece] = {}

    @property
    def height(self) -> int:
        return self._height

    @property
    def width(self) -> int:
        return self._width

    def is_inside(self, position: Position) -> bool:
        return 0 <= position.row < self._height and 0 <= position.col < self._width

    def piece_at(self, position: Position) -> Optional[Piece]:
        return self._pieces.get(position)

    def add_piece(self, piece: Piece) -> None:
        if piece.cell in self._pieces:
            raise CellOccupiedError(f"cell {piece.cell} is already occupied")
        self._pieces[piece.cell] = piece

    def remove_piece(self, piece: Piece) -> None:
        del self._pieces[piece.cell]

    def move_piece(self, piece: Piece, to: Position) -> None:
        """מזיז כלי שכבר אומת ליעד. לא בודק חוקיות ולא מזהה לכידה בעצמו -
        אם הקורא (בעתיד: RealTimeArbiter) צריך לדעת שהתרחשה לכידה, עליו
        לבדוק piece_at(to) *לפני* הקריאה לפונקציה הזו."""
        del self._pieces[piece.cell]
        piece.cell = to
        self._pieces[to] = piece

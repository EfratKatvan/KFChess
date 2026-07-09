from __future__ import annotations
from typing import Dict, Optional, Set

from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece


class CellOccupiedError(Exception):
    """נזרקת כשמנסים להוסיף כלי לתא שכבר תפוס ע"י כלי אחר."""


class DuplicatePieceIdError(Exception):
    """נזרקת כשמנסים להוסיף כלי עם id שכבר קיים על הלוח - הזהות היציבה
    של הכלי משמשת למעקב תנועה (RealTimeArbiter), אז היא חייבת להיות ייחודית."""


class Board:
    """אוסף הכלים החיים על הלוח - יודע רק מי נמצא איפה.
    לא יודע חוקי שחמט, פיקסלים, טקסט או תזמון."""

    def __init__(self, width: int, height: int) -> None:
        self._width = width
        self._height = height
        self._pieces: Dict[Position, Piece] = {}
        self._piece_ids: Set[str] = set()

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
        if piece.id in self._piece_ids:
            raise DuplicatePieceIdError(f"piece id {piece.id!r} is already on the board")
        self._pieces[piece.cell] = piece
        self._piece_ids.add(piece.id)

    def remove_piece(self, piece: Piece) -> None:
        del self._pieces[piece.cell]
        self._piece_ids.discard(piece.id)

    def move_piece(self, piece: Piece, to: Position) -> None:
        """מזיז כלי שכבר אומת ליעד. לא בודק חוקיות ולא מזהה לכידה בעצמו -
        אם הקורא צריך לדעת שהתרחשה לכידה, עליו לבדוק piece_at(to) *לפני*
        הקריאה לפונקציה הזו. אם התא כבר תפוס, הכלי שהיה שם מוסר בשקט
        (כדי שה-id שלו לא יישאר "תפוס" על הלוח לנצח)."""
        del self._pieces[piece.cell]
        displaced = self._pieces.get(to)
        if displaced is not None:
            self._piece_ids.discard(displaced.id)
        piece.cell = to
        self._pieces[to] = piece

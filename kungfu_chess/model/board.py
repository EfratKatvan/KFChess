from __future__ import annotations
from typing import Dict, Optional, Protocol, Set

from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, PieceRepresentation


class CellOccupiedError(Exception):
    """Raised when trying to add a piece to a cell already occupied by
    another piece."""


class DuplicatePieceIdError(Exception):
    """Raised when trying to add a piece whose id is already on the
    board - a piece's stable identity is used to track motion
    (RealTimeArbiter), so it must be unique."""


class BoardRepresentation(Protocol):
    """The shape rules/engine/realtime actually call on a board - Board
    (below) satisfies this structurally, without inheriting from it.
    move_piece is deliberately not part of this: nothing outside
    Board's own tests calls it, every real mutation goes through
    add_piece/remove_piece. See
    tests/unit/test_board_representation.py for a second, list-backed
    implementation proving rule/engine code runs unchanged against
    either one - the actual point of this Protocol."""

    @property
    def width(self) -> int: ...

    @property
    def height(self) -> int: ...

    def is_inside(self, position: Position) -> bool: ...

    def piece_at(self, position: Position) -> Optional[PieceRepresentation]: ...

    def add_piece(self, piece: PieceRepresentation) -> None: ...

    def remove_piece(self, piece: PieceRepresentation) -> None: ...


class Board:
    """The set of pieces currently on the board - only knows who's
    where. Knows nothing about chess rules, pixels, text, or timing."""

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
        """Moves an already-validated piece to its destination. Doesn't
        check legality or detect a capture itself - if the caller needs
        to know a capture happened, it must check piece_at(to) *before*
        calling this. If the cell is already occupied, the piece that
        was there is silently removed (so its id doesn't stay "occupied"
        on the board forever)."""
        del self._pieces[piece.cell]
        displaced = self._pieces.get(to)
        if displaced is not None:
            self._piece_ids.discard(displaced.id)
        piece.cell = to
        self._pieces[to] = piece

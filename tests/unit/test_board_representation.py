"""Proves BoardRepresentation/PieceRepresentation (kungfu_chess/model/board.py,
kungfu_chess/model/piece.py) are a real boundary, not just documentation:
rules/engine/realtime code runs unchanged against a second, list-backed
board that shares no code with the dict-backed Board it was written
against and tested with everywhere else."""

from typing import List, Optional

from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.model.board import CellOccupiedError, DuplicatePieceIdError
from kungfu_chess.model.piece import Piece, PieceRepresentation, WHITE, BLACK, ROOK, KING
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine


class ListBoard:
    """An alternative BoardRepresentation backed by a flat list instead
    of a dict (see kungfu_chess/model/board.py's Board) - exists only in
    this test file, purely to prove the split is real."""

    def __init__(self, width: int, height: int) -> None:
        self._width = width
        self._height = height
        self._pieces: List[PieceRepresentation] = []

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def is_inside(self, position: Position) -> bool:
        return 0 <= position.row < self._height and 0 <= position.col < self._width

    def piece_at(self, position: Position) -> Optional[PieceRepresentation]:
        for piece in self._pieces:
            if piece.cell == position:
                return piece
        return None

    def add_piece(self, piece: PieceRepresentation) -> None:
        if self.piece_at(piece.cell) is not None:
            raise CellOccupiedError(f"cell {piece.cell} is already occupied")
        if any(existing.id == piece.id for existing in self._pieces):
            raise DuplicatePieceIdError(f"piece id {piece.id!r} is already on the board")
        self._pieces.append(piece)

    def remove_piece(self, piece: PieceRepresentation) -> None:
        self._pieces.remove(piece)


def test_rule_engine_computes_legal_destinations_against_a_list_backed_board():
    board = ListBoard(width=3, height=3)
    board.add_piece(Piece(id="wR", color=WHITE, kind=ROOK, cell=Position(0, 0)))

    rule_engine = RuleEngine(board)

    assert rule_engine.legal_destinations(Position(0, 0)) == {
        Position(0, 1), Position(0, 2), Position(1, 0), Position(2, 0),
    }


def test_game_engine_and_arbiter_move_and_capture_against_a_list_backed_board():
    """Exercises the whole stack (GameEngine + RealTimeArbiter, not just
    RuleEngine's read-only validation) - a capture mutates the board via
    add_piece/remove_piece, and a king capture ends the game, both
    working identically against ListBoard as they do against Board."""
    board = ListBoard(width=3, height=1)
    rook = Piece(id="wR", color=WHITE, kind=ROOK, cell=Position(0, 0))
    king = Piece(id="bK", color=BLACK, kind=KING, cell=Position(0, 2))
    board.add_piece(rook)
    board.add_piece(king)

    engine = GameEngine(board, RuleEngine(board), RealTimeArbiter(board))

    result = engine.request_move(Position(0, 0), Position(0, 2))
    assert result.is_accepted is True

    engine.wait(2000)

    assert board.piece_at(Position(0, 2)) is rook
    assert board.piece_at(Position(0, 0)) is None
    assert engine.is_game_over() is True

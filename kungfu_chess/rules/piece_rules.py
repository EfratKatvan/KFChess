from __future__ import annotations
from typing import Protocol, Set

from kungfu_chess.model.board import BoardRepresentation
from kungfu_chess.model.piece import PieceRepresentation, WHITE, ROOK, BISHOP, QUEEN, KNIGHT, KING, PAWN
from kungfu_chess.model.position import Position


class PieceRule(Protocol):
    """The contract every piece-kind's movement rule must satisfy - an
    extension point: a new piece kind (or a replacement rule) can be
    added without touching RuleEngine, as long as it has a method with
    this signature."""

    def legal_destinations(self, board: BoardRepresentation, piece: PieceRepresentation) -> Set[Position]: ...

def _sliding_destinations(board: BoardRepresentation, piece: PieceRepresentation, directions) -> Set[Position]:
    destinations: Set[Position] = set()
    for dr, dc in directions:
        row, col = piece.cell.row + dr, piece.cell.col + dc
        position = Position(row, col)
        while board.is_inside(position):
            occupant = board.piece_at(position)
            if occupant is None:
                destinations.add(position)
            else:
                if occupant.color != piece.color:
                    destinations.add(position)
                break
            row += dr
            col += dc
            position = Position(row, col)
    return destinations

def _step_destinations(board: BoardRepresentation, piece: PieceRepresentation, offsets) -> Set[Position]:
    destinations: Set[Position] = set()
    for dr, dc in offsets:
        position = Position(piece.cell.row + dr, piece.cell.col + dc)
        if not board.is_inside(position):
            continue
        occupant = board.piece_at(position)
        if occupant is None or occupant.color != piece.color:
            destinations.add(position)
    return destinations


class RookRules:
    @staticmethod
    def legal_destinations(board: BoardRepresentation, piece: PieceRepresentation) -> Set[Position]:
        return _sliding_destinations(board, piece, [(1, 0), (-1, 0), (0, 1), (0, -1)])


class BishopRules:
    @staticmethod
    def legal_destinations(board: BoardRepresentation, piece: PieceRepresentation) -> Set[Position]:
        return _sliding_destinations(board, piece, [(1, 1), (1, -1), (-1, 1), (-1, -1)])


class QueenRules:
    @staticmethod
    def legal_destinations(board: BoardRepresentation, piece: PieceRepresentation) -> Set[Position]:
        return RookRules.legal_destinations(board, piece) | BishopRules.legal_destinations(board, piece)


class KnightRules:
    _OFFSETS = [(1, 2), (1, -2), (-1, 2), (-1, -2), (2, 1), (2, -1), (-2, 1), (-2, -1)]

    @staticmethod
    def legal_destinations(board: BoardRepresentation, piece: PieceRepresentation) -> Set[Position]:
        return _step_destinations(board, piece, KnightRules._OFFSETS)


class KingRules:
    _OFFSETS = [(dr, dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if (dr, dc) != (0, 0)]

    @staticmethod
    def legal_destinations(board: BoardRepresentation, piece: PieceRepresentation) -> Set[Position]:
        return _step_destinations(board, piece, KingRules._OFFSETS)


def _pawn_start_row(board: BoardRepresentation, color: str) -> int:
    """A pawn's starting row - one row in from its edge, at any board height."""
    return board.height - 2 if color == WHITE else 1


# Intentional: no en passant, no promotion here (that's in RealTimeArbiter).
class PawnRules:
    @staticmethod
    def legal_destinations(board: BoardRepresentation, piece: PieceRepresentation) -> Set[Position]:
        direction = -1 if piece.color == WHITE else 1
        destinations: Set[Position] = set()

        forward = Position(piece.cell.row + direction, piece.cell.col)
        if board.is_inside(forward) and board.piece_at(forward) is None:
            destinations.add(forward)

            if piece.cell.row == _pawn_start_row(board, piece.color):
                double_forward = Position(piece.cell.row + 2 * direction, piece.cell.col)
                if board.is_inside(double_forward) and board.piece_at(double_forward) is None:
                    destinations.add(double_forward)

        for dc in (-1, 1):
            diagonal = Position(piece.cell.row + direction, piece.cell.col + dc)
            if not board.is_inside(diagonal):
                continue
            occupant = board.piece_at(diagonal)
            if occupant is not None and occupant.color != piece.color:
                destinations.add(diagonal)

        return destinations


STANDARD_PIECE_RULES = {
    ROOK: RookRules,
    BISHOP: BishopRules,
    QUEEN: QueenRules,
    KNIGHT: KnightRules,
    KING: KingRules,
    PAWN: PawnRules,
}


def rules_for(kind: str):
    return STANDARD_PIECE_RULES[kind]

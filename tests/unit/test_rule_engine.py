from kungfu_chess.model.board import Board
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, WHITE, BLACK, ROOK, BISHOP, PAWN
from kungfu_chess.rules.rule_engine import (
    RuleEngine,
    REASON_OK,
    REASON_OUTSIDE_BOARD,
    REASON_EMPTY_SOURCE,
    REASON_FRIENDLY_DESTINATION,
    REASON_ILLEGAL_PIECE_MOVE,
)


def add(board, piece_id, color, kind, row, col):
    board.add_piece(Piece(id=piece_id, color=color, kind=kind, cell=Position(row, col)))


def test_legal_rook_move_is_valid_with_reason_ok():
    board = Board(width=3, height=1)
    add(board, "wR", WHITE, ROOK, 0, 0)
    result = RuleEngine(board).validate_move(Position(0, 0), Position(0, 2))
    assert result.is_valid is True
    assert result.reason == REASON_OK


def test_move_to_outside_the_board_is_rejected():
    board = Board(width=3, height=1)
    add(board, "wR", WHITE, ROOK, 0, 0)
    result = RuleEngine(board).validate_move(Position(0, 0), Position(0, 9))
    assert result.is_valid is False
    assert result.reason == REASON_OUTSIDE_BOARD


def test_move_from_outside_the_board_is_rejected():
    board = Board(width=3, height=1)
    result = RuleEngine(board).validate_move(Position(-1, 0), Position(0, 1))
    assert result.is_valid is False
    assert result.reason == REASON_OUTSIDE_BOARD


def test_legal_destinations_matches_the_pieces_own_rule():
    board = Board(width=3, height=1)
    add(board, "wR", WHITE, ROOK, 0, 0)
    assert RuleEngine(board).legal_destinations(Position(0, 0)) == {Position(0, 1), Position(0, 2)}


def test_legal_destinations_is_empty_for_an_empty_cell():
    board = Board(width=3, height=1)
    assert RuleEngine(board).legal_destinations(Position(0, 0)) == set()


def test_move_from_empty_source_is_rejected():
    board = Board(width=3, height=1)
    result = RuleEngine(board).validate_move(Position(0, 0), Position(0, 2))
    assert result.is_valid is False
    assert result.reason == REASON_EMPTY_SOURCE


def test_move_to_friendly_destination_is_rejected():
    board = Board(width=3, height=1)
    add(board, "wR", WHITE, ROOK, 0, 0)
    add(board, "wB", WHITE, BISHOP, 0, 2)
    result = RuleEngine(board).validate_move(Position(0, 0), Position(0, 2))
    assert result.is_valid is False
    assert result.reason == REASON_FRIENDLY_DESTINATION


def test_move_shaped_wrong_for_the_piece_is_rejected():
    board = Board(width=3, height=2)
    add(board, "wR", WHITE, ROOK, 0, 0)
    result = RuleEngine(board).validate_move(Position(0, 0), Position(1, 1))
    assert result.is_valid is False
    assert result.reason == REASON_ILLEGAL_PIECE_MOVE


def test_rook_blocked_by_piece_in_path_is_illegal_piece_move():
    board = Board(width=3, height=1)
    add(board, "wR", WHITE, ROOK, 0, 0)
    add(board, "wP", WHITE, PAWN, 0, 1)
    result = RuleEngine(board).validate_move(Position(0, 0), Position(0, 2))
    assert result.is_valid is False
    assert result.reason == REASON_ILLEGAL_PIECE_MOVE


def test_capturing_enemy_piece_is_valid():
    board = Board(width=3, height=1)
    add(board, "wR", WHITE, ROOK, 0, 0)
    add(board, "bR", BLACK, ROOK, 0, 2)
    result = RuleEngine(board).validate_move(Position(0, 0), Position(0, 2))
    assert result.is_valid is True
    assert result.reason == REASON_OK

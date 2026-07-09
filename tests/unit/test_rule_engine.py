from kungfu_chess.model.board import Board
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, WHITE, BLACK, ROOK, BISHOP, PAWN
from kungfu_chess.rules.rule_engine import RuleEngine


def add(board, piece_id, color, kind, row, col):
    board.add_piece(Piece(id=piece_id, color=color, kind=kind, cell=Position(row, col)))


def test_legal_rook_move_is_allowed():
    board = Board(width=3, height=1)
    add(board, "wR", WHITE, ROOK, 0, 0)
    rule_engine = RuleEngine(board)
    assert rule_engine.is_legal_move(Position(0, 0), Position(0, 2)) is True


def test_rook_move_blocked_by_piece_is_rejected():
    board = Board(width=3, height=1)
    add(board, "wR", WHITE, ROOK, 0, 0)
    add(board, "wP", WHITE, PAWN, 0, 1)
    rule_engine = RuleEngine(board)
    assert rule_engine.is_legal_move(Position(0, 0), Position(0, 2)) is False


def test_move_shaped_wrong_for_piece_is_rejected():
    board = Board(width=3, height=2)
    add(board, "wR", WHITE, ROOK, 0, 0)
    rule_engine = RuleEngine(board)
    assert rule_engine.is_legal_move(Position(0, 0), Position(1, 1)) is False


def test_capturing_own_color_piece_is_rejected():
    board = Board(width=3, height=1)
    add(board, "wR", WHITE, ROOK, 0, 0)
    add(board, "wB", WHITE, BISHOP, 0, 2)
    rule_engine = RuleEngine(board)
    assert rule_engine.is_legal_move(Position(0, 0), Position(0, 2)) is False


def test_capturing_enemy_piece_is_allowed():
    board = Board(width=3, height=1)
    add(board, "wR", WHITE, ROOK, 0, 0)
    add(board, "bR", BLACK, ROOK, 0, 2)
    rule_engine = RuleEngine(board)
    assert rule_engine.is_legal_move(Position(0, 0), Position(0, 2)) is True


def test_move_from_empty_cell_is_rejected():
    board = Board(width=3, height=1)
    rule_engine = RuleEngine(board)
    assert rule_engine.is_legal_move(Position(0, 0), Position(0, 2)) is False

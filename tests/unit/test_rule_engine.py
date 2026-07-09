from kungfu_chess.model.board import Board
from kungfu_chess.rules.rule_engine import RuleEngine


def test_legal_rook_move_is_allowed():
    board = Board.from_rows([["wR", ".", "."]])
    rule_engine = RuleEngine(board)
    assert rule_engine.is_legal_move("wR", (0, 0), (0, 2)) is True


def test_rook_move_blocked_by_piece_is_rejected():
    board = Board.from_rows([["wR", "wP", "."]])
    rule_engine = RuleEngine(board)
    assert rule_engine.is_legal_move("wR", (0, 0), (0, 2)) is False


def test_move_shaped_wrong_for_piece_is_rejected():
    board = Board.from_rows([["wR", ".", "."], [".", ".", "."]])
    rule_engine = RuleEngine(board)
    assert rule_engine.is_legal_move("wR", (0, 0), (1, 1)) is False


def test_capturing_own_color_piece_is_rejected():
    board = Board.from_rows([["wR", ".", "wB"]])
    rule_engine = RuleEngine(board)
    assert rule_engine.is_legal_move("wR", (0, 0), (0, 2)) is False


def test_capturing_enemy_piece_is_allowed():
    board = Board.from_rows([["wR", ".", "bR"]])
    rule_engine = RuleEngine(board)
    assert rule_engine.is_legal_move("wR", (0, 0), (0, 2)) is True

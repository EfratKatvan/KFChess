import pytest

from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, WHITE, BLACK, ROOK, KING
from kungfu_chess.model.board import Board, CellOccupiedError, DuplicatePieceIdError


def make_piece(piece_id, color, kind, row, col):
    return Piece(id=piece_id, color=color, kind=kind, cell=Position(row, col))


# ==========================================
# מידות הלוח
# ==========================================

def test_board_dimensions_are_reported_correctly():
    board = Board(width=3, height=2)
    assert board.width == 3
    assert board.height == 2


def test_empty_board_has_zero_dimensions():
    board = Board(width=0, height=0)
    assert board.width == 0
    assert board.height == 0


# ==========================================
# is_inside
# ==========================================

def test_is_inside_true_for_cell_within_bounds():
    board = Board(width=2, height=2)
    assert board.is_inside(Position(0, 0)) is True
    assert board.is_inside(Position(1, 1)) is True


def test_is_inside_false_for_cell_outside_bounds():
    board = Board(width=2, height=2)
    assert board.is_inside(Position(-1, 0)) is False
    assert board.is_inside(Position(0, 2)) is False
    assert board.is_inside(Position(2, 0)) is False


# ==========================================
# piece_at / add_piece
# ==========================================

def test_empty_cell_returns_no_piece():
    board = Board(width=1, height=1)
    assert board.piece_at(Position(0, 0)) is None


def test_occupied_cell_returns_the_correct_piece():
    board = Board(width=1, height=1)
    rook = make_piece("wR-0-0", WHITE, ROOK, 0, 0)
    board.add_piece(rook)
    assert board.piece_at(Position(0, 0)) is rook


def test_adding_two_pieces_to_the_same_cell_fails():
    board = Board(width=1, height=1)
    board.add_piece(make_piece("wR-0-0", WHITE, ROOK, 0, 0))
    with pytest.raises(CellOccupiedError):
        board.add_piece(make_piece("bK-0-0", BLACK, KING, 0, 0))


def test_adding_a_piece_with_a_duplicate_id_fails():
    board = Board(width=2, height=1)
    board.add_piece(make_piece("wR-1", WHITE, ROOK, 0, 0))
    with pytest.raises(DuplicatePieceIdError):
        board.add_piece(make_piece("wR-1", BLACK, KING, 0, 1))


def test_removing_a_piece_frees_its_id_for_reuse():
    board = Board(width=1, height=1)
    rook = make_piece("wR-1", WHITE, ROOK, 0, 0)
    board.add_piece(rook)
    board.remove_piece(rook)
    board.add_piece(make_piece("wR-1", BLACK, KING, 0, 0))  # לא אמור להיכשל


# ==========================================
# move_piece / remove_piece
# ==========================================

def test_moving_a_piece_updates_source_and_destination():
    board = Board(width=2, height=1)
    rook = make_piece("wR-0-0", WHITE, ROOK, 0, 0)
    board.add_piece(rook)

    board.move_piece(rook, Position(0, 1))

    assert board.piece_at(Position(0, 0)) is None
    assert board.piece_at(Position(0, 1)) is rook
    assert rook.cell == Position(0, 1)


def test_moving_a_piece_onto_an_occupied_cell_displaces_the_piece_there():
    board = Board(width=2, height=1)
    attacker = make_piece("wR-0-0", WHITE, ROOK, 0, 0)
    defender = make_piece("bR-0-1", BLACK, ROOK, 0, 1)
    board.add_piece(attacker)
    board.add_piece(defender)

    board.move_piece(attacker, Position(0, 1))

    assert board.piece_at(Position(0, 1)) is attacker


def test_displaced_piece_id_can_be_reused():
    board = Board(width=2, height=1)
    attacker = make_piece("wR-0-0", WHITE, ROOK, 0, 0)
    defender = make_piece("bR-0-1", BLACK, ROOK, 0, 1)
    board.add_piece(attacker)
    board.add_piece(defender)

    board.move_piece(attacker, Position(0, 1))  # "bR-0-1" נדחק מהלוח

    board.add_piece(make_piece("bR-0-1", BLACK, KING, 0, 0))  # לא אמור להיכשל


def test_removing_a_captured_piece_clears_its_cell():
    board = Board(width=1, height=1)
    rook = make_piece("wR-0-0", WHITE, ROOK, 0, 0)
    board.add_piece(rook)

    board.remove_piece(rook)

    assert board.piece_at(Position(0, 0)) is None

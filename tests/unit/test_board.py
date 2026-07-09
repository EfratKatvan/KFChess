from kungfu_chess.model.board import Board


def test_width_and_height():
    board = Board.from_rows([["wK", ".", "bK"], [".", ".", "."]])
    assert board.height == 2
    assert board.width == 3


def test_empty_board_dimensions():
    board = Board.from_rows([])
    assert board.height == 0
    assert board.width == 0


def test_to_rows_returns_matching_snapshot():
    board = Board.from_rows([["wK", ".", "bK"], [".", ".", "."]])
    assert board.to_rows() == [["wK", ".", "bK"], [".", ".", "."]]


def test_to_rows_returns_a_copy_not_the_internal_state():
    board = Board.from_rows([["wK"]])
    snapshot = board.to_rows()
    snapshot[0][0] = "bK"
    assert board.get_cell(0, 0) == "wK"


def test_is_inside_true_for_cell_within_bounds():
    board = Board.from_rows([["wK", "."], [".", "."]])
    assert board.is_inside(0, 0) is True
    assert board.is_inside(1, 1) is True


def test_is_inside_false_for_cell_outside_bounds():
    board = Board.from_rows([["wK", "."], [".", "."]])
    assert board.is_inside(-1, 0) is False
    assert board.is_inside(0, 2) is False
    assert board.is_inside(2, 0) is False


def test_get_cell_on_empty_square_returns_empty_marker():
    board = Board.from_rows([["."]])
    assert board.get_cell(0, 0) == "."


def test_get_cell_on_occupied_square_returns_piece_token():
    board = Board.from_rows([["wR"]])
    assert board.get_cell(0, 0) == "wR"


def test_set_cell_updates_the_cell():
    board = Board.from_rows([["."]])
    board.set_cell(0, 0, "wQ")
    assert board.get_cell(0, 0) == "wQ"


def test_move_piece_updates_source_and_destination():
    board = Board.from_rows([["wR", "."]])
    board.move_piece(0, 0, 0, 1)
    assert board.get_cell(0, 0) == "."
    assert board.get_cell(0, 1) == "wR"


def test_move_piece_onto_occupied_destination_captures_it():
    board = Board.from_rows([["wR", "bR"]])
    board.move_piece(0, 0, 0, 1)
    assert board.get_cell(0, 0) == "."
    assert board.get_cell(0, 1) == "wR"

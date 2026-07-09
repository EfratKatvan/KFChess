from kungfu_chess.model.board import Board
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter


def test_piece_does_not_move_before_arrival_time():
    board = Board.from_rows([["wR", ".", "."]])
    arbiter = RealTimeArbiter(board)
    arbiter.start_motion("wR", (0, 0), (0, 2))  # distance 2 -> 2000ms

    arbiter.advance(1000)  # חצי דרך

    assert board.get_cell(0, 0) == "wR"
    assert board.get_cell(0, 2) == "."


def test_piece_arrives_after_full_travel_time():
    board = Board.from_rows([["wR", ".", "."]])
    arbiter = RealTimeArbiter(board)
    arbiter.start_motion("wR", (0, 0), (0, 2))

    arbiter.advance(2000)

    assert board.get_cell(0, 0) == "."
    assert board.get_cell(0, 2) == "wR"


def test_advance_can_be_split_across_multiple_calls():
    board = Board.from_rows([["wR", ".", "."]])
    arbiter = RealTimeArbiter(board)
    arbiter.start_motion("wR", (0, 0), (0, 2))

    arbiter.advance(1000)
    arbiter.advance(1000)

    assert board.get_cell(0, 2) == "wR"


def test_arriving_piece_captures_enemy_piece():
    board = Board.from_rows([["wR", ".", "bR"]])
    arbiter = RealTimeArbiter(board)
    arbiter.start_motion("wR", (0, 0), (0, 2))

    king_captured = arbiter.advance(2000)

    assert board.get_cell(0, 2) == "wR"
    assert king_captured is False


def test_capturing_a_king_is_reported():
    board = Board.from_rows([["wR", ".", "bK"]])
    arbiter = RealTimeArbiter(board)
    arbiter.start_motion("wR", (0, 0), (0, 2))

    king_captured = arbiter.advance(2000)

    assert king_captured is True
    assert board.get_cell(0, 2) == "wR"


def test_pawn_reaching_last_row_is_promoted_to_queen():
    board = Board.from_rows([[".", "."], ["wP", "."]])
    arbiter = RealTimeArbiter(board)
    arbiter.start_motion("wP", (1, 0), (0, 0))

    arbiter.advance(1000)

    assert board.get_cell(0, 0) == "wQ"


def test_is_destination_reserved_true_while_a_motion_targets_it():
    board = Board.from_rows([["wR", ".", "wB"]])
    arbiter = RealTimeArbiter(board)
    arbiter.start_motion("wR", (0, 0), (0, 1))

    assert arbiter.is_destination_reserved(0, 1) is True
    assert arbiter.is_destination_reserved(0, 2) is False


def test_is_cell_busy_true_for_motion_source_and_destination():
    board = Board.from_rows([["wR", ".", "."]])
    arbiter = RealTimeArbiter(board)
    arbiter.start_motion("wR", (0, 0), (0, 2))

    assert arbiter.is_cell_busy(0, 0) is True
    assert arbiter.is_cell_busy(0, 2) is True
    assert arbiter.is_cell_busy(0, 1) is False


def test_jump_does_not_count_as_busy():
    board = Board.from_rows([["wK"]])
    arbiter = RealTimeArbiter(board)
    arbiter.start_jump(0, 0)

    assert arbiter.is_cell_busy(0, 0) is False
    assert arbiter.is_cell_airborne(0, 0) is True


def test_jump_saves_piece_from_arriving_enemy():
    board = Board.from_rows([["wK", "bR", "."]])
    arbiter = RealTimeArbiter(board)
    arbiter.start_jump(0, 0)
    arbiter.start_motion("bR", (0, 1), (0, 0))

    king_captured = arbiter.advance(1000)

    assert board.get_cell(0, 0) == "wK"
    assert king_captured is False


def test_jump_expires_after_its_duration():
    board = Board.from_rows([["wK", "."]])
    arbiter = RealTimeArbiter(board)
    arbiter.start_jump(0, 0)

    arbiter.advance(1000)

    assert arbiter.is_cell_airborne(0, 0) is False

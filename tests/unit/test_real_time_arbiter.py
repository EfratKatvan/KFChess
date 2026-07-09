from kungfu_chess.model.board import Board
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, WHITE, BLACK, ROOK, BISHOP, KING, QUEEN, PAWN, IDLE, MOVING, CAPTURED
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter


def add(board, piece_id, color, kind, row, col):
    piece = Piece(id=piece_id, color=color, kind=kind, cell=Position(row, col))
    board.add_piece(piece)
    return piece


def test_piece_does_not_move_before_arrival_time():
    board = Board(width=3, height=1)
    rook = add(board, "wR", WHITE, ROOK, 0, 0)
    arbiter = RealTimeArbiter(board)
    arbiter.start_motion(rook, Position(0, 2))  # distance 2 -> 2000ms

    arbiter.advance_time(1000)  # חצי דרך

    assert board.piece_at(Position(0, 0)) is rook
    assert board.piece_at(Position(0, 2)) is None


def test_piece_arrives_after_full_travel_time():
    board = Board(width=3, height=1)
    rook = add(board, "wR", WHITE, ROOK, 0, 0)
    arbiter = RealTimeArbiter(board)
    arbiter.start_motion(rook, Position(0, 2))

    arbiter.advance_time(2000)

    assert board.piece_at(Position(0, 0)) is None
    assert board.piece_at(Position(0, 2)) is rook
    assert rook.cell == Position(0, 2)
    assert rook.state == IDLE


def test_advance_can_be_split_across_multiple_calls():
    board = Board(width=3, height=1)
    rook = add(board, "wR", WHITE, ROOK, 0, 0)
    arbiter = RealTimeArbiter(board)
    arbiter.start_motion(rook, Position(0, 2))

    arbiter.advance_time(1000)
    arbiter.advance_time(1000)

    assert board.piece_at(Position(0, 2)) is rook


def test_arriving_piece_captures_enemy_piece():
    board = Board(width=3, height=1)
    rook = add(board, "wR", WHITE, ROOK, 0, 0)
    enemy = add(board, "bR", BLACK, ROOK, 0, 2)
    arbiter = RealTimeArbiter(board)
    arbiter.start_motion(rook, Position(0, 2))

    king_captured = arbiter.advance_time(2000)

    assert board.piece_at(Position(0, 2)) is rook
    assert enemy.state == CAPTURED
    assert king_captured is False


def test_capturing_a_king_is_reported():
    board = Board(width=3, height=1)
    rook = add(board, "wR", WHITE, ROOK, 0, 0)
    add(board, "bK", BLACK, KING, 0, 2)
    arbiter = RealTimeArbiter(board)
    arbiter.start_motion(rook, Position(0, 2))

    king_captured = arbiter.advance_time(2000)

    assert king_captured is True
    assert board.piece_at(Position(0, 2)) is rook


def test_pawn_reaching_last_row_is_promoted_to_queen():
    board = Board(width=2, height=2)
    pawn = add(board, "wP", WHITE, PAWN, 1, 0)
    arbiter = RealTimeArbiter(board)
    arbiter.start_motion(pawn, Position(0, 0))

    arbiter.advance_time(1000)

    assert pawn.kind == QUEEN
    assert board.piece_at(Position(0, 0)) is pawn


def test_is_destination_reserved_true_while_a_motion_targets_it():
    board = Board(width=3, height=1)
    rook = add(board, "wR", WHITE, ROOK, 0, 0)
    add(board, "wB", WHITE, BISHOP, 0, 2)
    arbiter = RealTimeArbiter(board)
    arbiter.start_motion(rook, Position(0, 1))

    assert arbiter.is_destination_reserved(Position(0, 1)) is True
    assert arbiter.is_destination_reserved(Position(0, 2)) is False


def test_is_cell_busy_true_for_motion_source_and_destination():
    board = Board(width=3, height=1)
    rook = add(board, "wR", WHITE, ROOK, 0, 0)
    arbiter = RealTimeArbiter(board)
    arbiter.start_motion(rook, Position(0, 2))

    assert arbiter.is_cell_busy(Position(0, 0)) is True
    assert arbiter.is_cell_busy(Position(0, 2)) is True
    assert arbiter.is_cell_busy(Position(0, 1)) is False


def test_starting_a_motion_marks_the_piece_as_moving():
    board = Board(width=3, height=1)
    rook = add(board, "wR", WHITE, ROOK, 0, 0)
    arbiter = RealTimeArbiter(board)
    arbiter.start_motion(rook, Position(0, 2))
    assert rook.state == MOVING


def test_jump_does_not_count_as_busy():
    board = Board(width=1, height=1)
    add(board, "wK", WHITE, KING, 0, 0)
    arbiter = RealTimeArbiter(board)
    arbiter.start_jump(Position(0, 0))

    assert arbiter.is_cell_busy(Position(0, 0)) is False
    assert arbiter.is_cell_airborne(Position(0, 0)) is True


def test_jump_saves_piece_from_arriving_enemy():
    board = Board(width=3, height=1)
    king = add(board, "wK", WHITE, KING, 0, 0)
    enemy = add(board, "bR", BLACK, ROOK, 0, 1)
    arbiter = RealTimeArbiter(board)
    arbiter.start_jump(Position(0, 0))
    arbiter.start_motion(enemy, Position(0, 0))

    king_captured = arbiter.advance_time(1000)

    assert board.piece_at(Position(0, 0)) is king
    assert king_captured is False


def test_jump_expires_after_its_duration():
    board = Board(width=2, height=1)
    add(board, "wK", WHITE, KING, 0, 0)
    arbiter = RealTimeArbiter(board)
    arbiter.start_jump(Position(0, 0))

    arbiter.advance_time(1000)

    assert arbiter.is_cell_airborne(Position(0, 0)) is False

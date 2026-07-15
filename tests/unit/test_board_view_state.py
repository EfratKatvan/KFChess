from kungfu_chess.engine.board_view_state import build_board_view_state
from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import Piece, WHITE, ROOK, KING
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.motion import LONG_REST, SHORT_REST, motion_duration_ms
from kungfu_chess.realtime.real_time_arbiter import JUMP_DURATION_MS, RealTimeArbiter


def add(board, piece_id, color, kind, row, col):
    piece = Piece(id=piece_id, color=color, kind=kind, cell=Position(row, col))
    board.add_piece(piece)
    return piece


def test_build_board_view_state_reports_board_dimensions_and_game_over():
    board = Board(width=2, height=3)
    arbiter = RealTimeArbiter(board)

    view_state = build_board_view_state(board, arbiter, game_over=True, total_elapsed_ms=0)

    assert (view_state.width, view_state.height) == (2, 3)
    assert view_state.game_over is True
    assert view_state.pieces == ()


def test_idle_piece_uses_idle_state_and_wall_clock_progress():
    board = Board(width=1, height=1)
    add(board, "wR", WHITE, ROOK, 0, 0)
    arbiter = RealTimeArbiter(board)

    [piece_view] = build_board_view_state(board, arbiter, game_over=False, total_elapsed_ms=1234).pieces

    assert piece_view.position == Position(0, 0)
    assert piece_view.color == WHITE
    assert piece_view.kind == ROOK
    assert piece_view.visual_state == "idle"
    assert piece_view.elapsed_ms == 1234
    assert piece_view.target_position is None
    assert piece_view.progress is None
    assert piece_view.remaining_fraction is None


def test_moving_piece_reports_move_state_with_target_and_progress():
    board = Board(width=3, height=1)
    rook = add(board, "wR", WHITE, ROOK, 0, 0)
    arbiter = RealTimeArbiter(board)
    arbiter.start_motion(rook, Position(0, 2))
    duration = motion_duration_ms(Position(0, 0), Position(0, 2))
    arbiter.advance_time(duration // 2)  # half-way

    [piece_view] = build_board_view_state(board, arbiter, game_over=False, total_elapsed_ms=0).pieces

    assert piece_view.visual_state == "move"
    assert piece_view.target_position == Position(0, 2)
    assert piece_view.elapsed_ms == duration // 2
    assert piece_view.progress == 0.5


def test_jumping_piece_reports_jump_state_at_its_own_cell():
    board = Board(width=1, height=1)
    add(board, "wK", WHITE, KING, 0, 0)
    arbiter = RealTimeArbiter(board)
    arbiter.start_jump(Position(0, 0))
    arbiter.advance_time(400)

    [piece_view] = build_board_view_state(board, arbiter, game_over=False, total_elapsed_ms=0).pieces

    assert piece_view.visual_state == "jump"
    assert piece_view.elapsed_ms == 400
    assert piece_view.target_position is None


def test_cooling_down_after_jump_reports_short_rest_and_full_remaining_fraction():
    board = Board(width=1, height=1)
    add(board, "wK", WHITE, KING, 0, 0)
    arbiter = RealTimeArbiter(board)
    arbiter.start_jump(Position(0, 0))
    arbiter.advance_time(JUMP_DURATION_MS)  # jump ends, short_rest starts fresh this same tick

    [piece_view] = build_board_view_state(board, arbiter, game_over=False, total_elapsed_ms=0).pieces

    assert piece_view.visual_state == SHORT_REST
    assert piece_view.elapsed_ms == 0
    assert piece_view.remaining_fraction == 1.0


def test_cooling_down_after_move_reports_long_rest():
    board = Board(width=2, height=1)
    rook = add(board, "wR", WHITE, ROOK, 0, 0)
    arbiter = RealTimeArbiter(board)
    arbiter.start_motion(rook, Position(0, 1))
    duration = motion_duration_ms(Position(0, 0), Position(0, 1))
    arbiter.advance_time(duration)  # arrives, long_rest starts fresh this same tick

    [piece_view] = build_board_view_state(board, arbiter, game_over=False, total_elapsed_ms=0).pieces

    assert piece_view.visual_state == LONG_REST
    assert piece_view.remaining_fraction == 1.0

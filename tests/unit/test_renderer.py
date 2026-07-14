from kungfu_chess.assets_config import PIECE_SETS, asset_code
from kungfu_chess.model.board import Board
from kungfu_chess.model.game_snapshot import GameSnapshot
from kungfu_chess.model.piece import Piece, WHITE, BLACK, ROOK, KING, PAWN, QUEEN
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.motion import Cooldown, Jump, Motion, LONG_REST, SHORT_REST, motion_duration_ms
from kungfu_chess.realtime.real_time_arbiter import COOLDOWN_DURATION_MS, JUMP_DURATION_MS, SHORT_REST_DURATION_MS
from kungfu_chess.view.renderer import Renderer, resolve_visual_state


def make_piece(piece_id, color, kind, row, col):
    return Piece(id=piece_id, color=color, kind=kind, cell=Position(row, col))


def test_idle_piece_uses_idle_state_and_wall_clock_progress():
    board = Board(width=1, height=1)
    piece = make_piece("wR", WHITE, ROOK, 0, 0)
    board.add_piece(piece)
    snapshot = GameSnapshot(board=board, game_over=False)

    state, elapsed_ms, pixel_pos = resolve_visual_state(piece, snapshot, total_elapsed_ms=1234, cell_size=100)

    assert state == "idle"
    assert elapsed_ms == 1234
    assert pixel_pos == (0, 0)


def test_moving_piece_reports_move_state_with_interpolated_pixel_position():
    board = Board(width=3, height=1)
    piece = make_piece("wR", WHITE, ROOK, 0, 0)
    board.add_piece(piece)
    duration = motion_duration_ms(Position(0, 0), Position(0, 2))
    motion = Motion(piece=piece, to_pos=Position(0, 2), remaining_ms=duration // 2)  # half-way through the move
    snapshot = GameSnapshot(board=board, game_over=False, motions=[motion])

    state, elapsed_ms, pixel_pos = resolve_visual_state(piece, snapshot, total_elapsed_ms=0, cell_size=100)

    assert state == "move"
    assert elapsed_ms == duration - duration // 2
    assert pixel_pos == (100, 0)  # half-way between col 0 and col 2, at cell_size=100


def test_jumping_piece_reports_jump_state_at_its_own_cell():
    board = Board(width=1, height=1)
    piece = make_piece("wK", WHITE, KING, 0, 0)
    board.add_piece(piece)
    jump = Jump(position=Position(0, 0), remaining_ms=400)
    snapshot = GameSnapshot(board=board, game_over=False, jumps=[jump])

    state, elapsed_ms, pixel_pos = resolve_visual_state(piece, snapshot, total_elapsed_ms=0, cell_size=100)

    assert state == "jump"
    assert elapsed_ms == JUMP_DURATION_MS - 400
    assert pixel_pos == (0, 0)


def test_cooling_down_piece_reports_its_cooldown_kind():
    board = Board(width=1, height=1)
    piece = make_piece("wR", WHITE, ROOK, 0, 0)
    board.add_piece(piece)
    cooldown = Cooldown(position=Position(0, 0), remaining_ms=250, kind=SHORT_REST)
    snapshot = GameSnapshot(board=board, game_over=False, cooldowns=[cooldown])

    state, elapsed_ms, _ = resolve_visual_state(piece, snapshot, total_elapsed_ms=0, cell_size=100)

    assert state == SHORT_REST
    assert elapsed_ms == SHORT_REST_DURATION_MS - 250


def test_long_rest_cooldown_uses_the_regular_cooldown_duration():
    board = Board(width=1, height=1)
    piece = make_piece("wR", WHITE, ROOK, 0, 0)
    board.add_piece(piece)
    cooldown = Cooldown(position=Position(0, 0), remaining_ms=300, kind=LONG_REST)
    snapshot = GameSnapshot(board=board, game_over=False, cooldowns=[cooldown])

    state, elapsed_ms, _ = resolve_visual_state(piece, snapshot, total_elapsed_ms=0, cell_size=100)

    assert state == LONG_REST
    assert elapsed_ms == COOLDOWN_DURATION_MS - 300


def test_asset_code_converts_project_token_order_to_ctd26_order():
    white_pawn = make_piece("wP", WHITE, PAWN, 0, 0)
    black_king = make_piece("bK", BLACK, KING, 0, 0)
    assert asset_code(white_pawn) == "PW"
    assert asset_code(black_king) == "KB"


def test_draw_returns_a_canvas_sized_to_the_board_in_pixels():
    board = Board(width=2, height=3)
    board.add_piece(make_piece("wR", WHITE, ROOK, 0, 0))
    snapshot = GameSnapshot(board=board, game_over=False)

    canvas = Renderer().draw(snapshot, total_elapsed_ms=0, cell_size=100)

    height, width = canvas.img.shape[:2]
    assert (width, height) == (200, 300)


def test_draw_accepts_either_piece_set():
    board = Board(width=1, height=1)
    board.add_piece(make_piece("wQ", WHITE, QUEEN, 0, 0))
    snapshot = GameSnapshot(board=board, game_over=False)
    renderer = Renderer()

    for piece_set in PIECE_SETS:
        canvas = renderer.draw(snapshot, total_elapsed_ms=0, cell_size=100, piece_set=piece_set)
        assert canvas.img is not None


def test_draw_reuses_injected_caches_across_calls():
    """שני Renderer עם אותם cache מוזרק חולקים אנימציות טעונות; שני
    Renderer בלי הזרקה (ברירת מחדל) לא."""
    from kungfu_chess.view.animation import AnimationCache
    from kungfu_chess.view.board_view import BoardView

    shared_cache = AnimationCache()
    shared_board_view = BoardView()
    board = Board(width=1, height=1)
    board.add_piece(make_piece("wR", WHITE, ROOK, 0, 0))
    snapshot = GameSnapshot(board=board, game_over=False)

    Renderer(animation_cache=shared_cache, board_view=shared_board_view).draw(snapshot, total_elapsed_ms=0, cell_size=100)

    assert len(shared_cache._animations) == 1
    assert len(shared_board_view._backgrounds) == 1

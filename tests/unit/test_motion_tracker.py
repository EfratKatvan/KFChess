from kungfu_chess.client.client_state import PendingMotion
from kungfu_chess.client.motion_tracker import apply_pending_motions
from kungfu_chess.engine.board_view_state import BoardViewState, PieceView
from kungfu_chess.model.piece import PAWN, WHITE
from kungfu_chess.model.position import Position


def _idle_piece(position):
    return PieceView(position=position, color=WHITE, kind=PAWN, visual_state="idle", elapsed_ms=0)


def test_apply_pending_motions_is_a_no_op_with_nothing_pending():
    view_state = BoardViewState(width=8, height=8, game_over=False, pieces=(_idle_piece(Position(6, 0)),))

    result = apply_pending_motions(view_state, pending_motions={}, now=1.0)

    assert result == view_state


def test_apply_pending_motions_overrides_an_active_motions_piece_view():
    view_state = BoardViewState(width=8, height=8, game_over=False, pieces=(_idle_piece(Position(6, 0)),))
    motion = PendingMotion(from_position=Position(6, 0), to_position=Position(5, 0), duration_ms=1000, started_at=0.0)

    result = apply_pending_motions(view_state, pending_motions={Position(6, 0): motion}, now=0.5)  # 500ms in

    [piece] = result.pieces
    assert piece.target_position == Position(5, 0)
    assert piece.progress == 0.5
    assert piece.visual_state == "move"
    assert piece.elapsed_ms == 500


def test_apply_pending_motions_leaves_unrelated_pieces_untouched():
    other = _idle_piece(Position(1, 1))
    view_state = BoardViewState(width=8, height=8, game_over=False, pieces=(_idle_piece(Position(6, 0)), other))
    motion = PendingMotion(from_position=Position(6, 0), to_position=Position(5, 0), duration_ms=1000, started_at=0.0)

    result = apply_pending_motions(view_state, pending_motions={Position(6, 0): motion}, now=0.5)

    assert other in result.pieces


def test_apply_pending_motions_stops_overriding_once_the_duration_has_elapsed():
    view_state = BoardViewState(width=8, height=8, game_over=False, pieces=(_idle_piece(Position(6, 0)),))
    motion = PendingMotion(from_position=Position(6, 0), to_position=Position(5, 0), duration_ms=1000, started_at=0.0)

    result = apply_pending_motions(view_state, pending_motions={Position(6, 0): motion}, now=2.0)  # well past 1000ms

    [piece] = result.pieces
    assert piece == _idle_piece(Position(6, 0))  # untouched - the (now stale) message data is left as-is

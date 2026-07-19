from kungfu_chess.engine.board_view_state import BoardViewState, MoveLogEntry, PieceView
from kungfu_chess.model.piece import WHITE, BLACK, PAWN, ROOK
from kungfu_chess.model.position import Position
from kungfu_chess.server.serialization import (
    board_view_state_from_wire,
    board_view_state_to_wire,
    legal_destinations_from_wire,
    legal_destinations_to_wire,
    position_from_wire,
    position_to_wire,
)


def test_position_round_trips():
    assert position_from_wire(position_to_wire(Position(3, 4))) == Position(3, 4)


def test_position_none_round_trips():
    assert position_from_wire(position_to_wire(None)) is None


def test_legal_destinations_round_trips_a_set_of_positions():
    destinations = {Position(1, 1), Position(2, 2)}
    assert legal_destinations_from_wire(legal_destinations_to_wire(destinations)) == destinations


def test_board_view_state_round_trips_a_mid_motion_piece_with_cooldown_move_log_and_scores():
    """One snapshot exercising everything a real game tick can contain -
    a piece mid-move (target_position/progress set), plus populated
    move_log/scores - the exact shape GameRoom broadcasts every tick."""
    state = BoardViewState(
        width=8,
        height=8,
        game_over=False,
        pieces=(
            PieceView(
                position=Position(4, 4), color=WHITE, kind=ROOK, visual_state="move",
                elapsed_ms=300, target_position=Position(4, 6), progress=0.5, remaining_fraction=None,
            ),
            PieceView(
                position=Position(2, 2), color=BLACK, kind=PAWN, visual_state="short_rest",
                elapsed_ms=1200, target_position=None, progress=None, remaining_fraction=0.4,
            ),
        ),
        scores={WHITE: 9, BLACK: 3},
        move_log={
            WHITE: (MoveLogEntry(elapsed_ms=0, from_pos=Position(6, 4), to_pos=Position(4, 4), kind=ROOK, is_capture=False),),
            BLACK: (),
        },
    )

    wire = board_view_state_to_wire(state)
    rebuilt = board_view_state_from_wire(wire)

    assert rebuilt == state


def test_board_view_state_round_trips_an_empty_board():
    state = BoardViewState(width=8, height=8, game_over=True, pieces=(), scores={}, move_log={})
    assert board_view_state_from_wire(board_view_state_to_wire(state)) == state

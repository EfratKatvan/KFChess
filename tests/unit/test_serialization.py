from kungfu_chess.engine.board_view_state import BoardViewState, MoveLogEntry, PieceView
from kungfu_chess.model.piece import WHITE, BLACK, PAWN, ROOK
from kungfu_chess.model.position import Position
from kungfu_chess.server.messages import (
    JumpMessage,
    LoginFailedMessage,
    LoginMessage,
    LoginOkMessage,
    MatchFoundMessage,
    NoOpponentFoundMessage,
    RestartMessage,
    SelectOrMoveMessage,
    StateMessage,
    WaitingForOpponentMessage,
)
from kungfu_chess.server.serialization import (
    board_view_state_from_wire,
    board_view_state_to_wire,
    deserialize_message,
    legal_destinations_from_wire,
    legal_destinations_to_wire,
    message_from_wire,
    message_to_wire,
    position_from_wire,
    position_to_wire,
    serialize_message,
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


# ==========================================
# message_to_wire / message_from_wire - the typed envelopes in server/messages.py
# ==========================================

def test_login_message_round_trips_username_and_password():
    original = LoginMessage(username="efrat", password="hunter2")
    assert message_from_wire(message_to_wire(original)) == original


def test_login_ok_message_round_trips_the_rating():
    original = LoginOkMessage(rating=1216)
    assert message_from_wire(message_to_wire(original)) == original


def test_login_failed_message_round_trips_the_reason():
    original = LoginFailedMessage(reason="wrong password")
    assert message_from_wire(message_to_wire(original)) == original


def test_waiting_for_opponent_message_round_trips():
    assert message_from_wire(message_to_wire(WaitingForOpponentMessage())) == WaitingForOpponentMessage()


def test_no_opponent_found_message_round_trips():
    assert message_from_wire(message_to_wire(NoOpponentFoundMessage())) == NoOpponentFoundMessage()


def test_match_found_message_round_trips_the_assigned_color():
    assert message_from_wire(message_to_wire(MatchFoundMessage(color=WHITE))) == MatchFoundMessage(color=WHITE)


def test_select_or_move_message_round_trips_row_and_col():
    original = SelectOrMoveMessage(row=3, col=5)
    assert message_from_wire(message_to_wire(original)) == original


def test_jump_message_round_trips_row_and_col():
    original = JumpMessage(row=2, col=6)
    assert message_from_wire(message_to_wire(original)) == original


def test_restart_message_round_trips():
    assert message_from_wire(message_to_wire(RestartMessage())) == RestartMessage()


def test_state_message_round_trips_board_selection_and_highlights():
    board = BoardViewState(width=8, height=8, game_over=False, pieces=(), scores={WHITE: 1}, move_log={})
    original = StateMessage(
        board=board,
        your_selected_pos=Position(1, 1),
        your_legal_destinations={Position(2, 1), Position(3, 1)},
        your_invalid_target=None,
    )
    assert message_from_wire(message_to_wire(original)) == original


def test_serialize_and_deserialize_message_round_trip_through_an_actual_json_string():
    """The end-to-end path every real message actually takes over the
    wire - serialize_message produces a str (what ws.send() takes),
    deserialize_message consumes one (what async for raw in ws yields)."""
    original = MatchFoundMessage(color=BLACK)
    raw = serialize_message(original)
    assert isinstance(raw, str)
    assert deserialize_message(raw) == original

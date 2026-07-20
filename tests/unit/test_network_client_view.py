from kungfu_chess.engine.board_view_state import BoardViewState
from kungfu_chess.model.piece import WHITE
from kungfu_chess.model.position import Position
from kungfu_chess.server.messages import (
    LoginFailedMessage,
    LoginOkMessage,
    MatchFoundMessage,
    OpponentDisconnectedMessage,
    OpponentReconnectedMessage,
    StateMessage,
)
from kungfu_chess.server.serialization import serialize_message
from kungfu_chess.view.network_client_view import (
    ClientBox,
    _disconnect_text,
    _game_over_started_at,
    _handle_message,
    _starting_text,
)


def test_starting_text_counts_down_before_go():
    assert _starting_text(WHITE, remaining_s=2.5) == "You are White - starting in 3..."


def test_starting_text_shows_go_once_time_is_up():
    assert _starting_text(WHITE, remaining_s=0.0) == "You are White - GO!"
    assert _starting_text(WHITE, remaining_s=-0.5) == "You are White - GO!"


def test_starting_text_omits_the_color_prefix_when_color_is_unknown():
    assert _starting_text(None, remaining_s=1.0) == "starting in 2..."


def test_game_over_started_at_is_none_while_the_game_is_still_playing():
    assert _game_over_started_at(previous=None, board_game_over=False) is None
    assert _game_over_started_at(previous=123.0, board_game_over=False) is None


def test_game_over_started_at_is_set_once_the_game_ends():
    result = _game_over_started_at(previous=None, board_game_over=True)
    assert result is not None


def test_game_over_started_at_keeps_the_original_timestamp_across_later_ticks():
    assert _game_over_started_at(previous=42.0, board_game_over=True) == 42.0


def test_handle_message_login_ok_stores_the_rating_and_stays_in_the_connecting_phase():
    box = ClientBox()
    _handle_message(serialize_message(LoginOkMessage(rating=1234)), box)

    assert box.state.phase == "connecting"  # server moves straight on to matchmaking next, no separate "logged in" phase
    assert box.state.rating == 1234


def test_handle_message_login_failed_sets_the_terminal_phase_and_reason():
    box = ClientBox()
    _handle_message(serialize_message(LoginFailedMessage(reason="wrong password")), box)

    assert box.state.phase == "login_failed"
    assert box.state.login_failure_reason == "wrong password"


def test_handle_message_match_found_sets_phase_color_and_matched_at():
    box = ClientBox()
    _handle_message(serialize_message(MatchFoundMessage(color=WHITE)), box)

    assert box.state.phase == "matched"
    assert box.state.color == WHITE
    assert box.state.matched_at is not None


def test_handle_message_state_carries_forward_color_and_matched_at():
    box = ClientBox()
    _handle_message(serialize_message(MatchFoundMessage(color=WHITE)), box)
    matched_at_before = box.state.matched_at

    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state_message = StateMessage(board=board, your_selected_pos=None, your_legal_destinations=set(), your_invalid_target=None)
    _handle_message(serialize_message(state_message), box)

    assert box.state.color == WHITE
    assert box.state.matched_at == matched_at_before
    assert box.state.view_state == board
    assert box.state.game_over_started_at is None


def test_handle_message_state_sets_game_over_started_at_once_the_game_ends():
    box = ClientBox()
    _handle_message(serialize_message(MatchFoundMessage(color=WHITE)), box)

    ended_board = BoardViewState(width=8, height=8, game_over=True, pieces=())
    state_message = StateMessage(board=ended_board, your_selected_pos=None, your_legal_destinations=set(), your_invalid_target=None)
    _handle_message(serialize_message(state_message), box)

    assert box.state.game_over_started_at is not None


def test_disconnect_text_counts_down_before_resigning():
    assert _disconnect_text(remaining_s=5.5) == "Opponent disconnected - auto-resign in 6..."


def test_disconnect_text_shows_resigning_once_time_is_up():
    assert _disconnect_text(remaining_s=0.0) == "Opponent disconnected - resigning..."
    assert _disconnect_text(remaining_s=-1.0) == "Opponent disconnected - resigning..."


def test_handle_message_opponent_disconnected_sets_the_countdown_fields_without_losing_board_state():
    box = ClientBox()
    _handle_message(serialize_message(MatchFoundMessage(color=WHITE)), box)
    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    _handle_message(
        serialize_message(StateMessage(board=board, your_selected_pos=None, your_legal_destinations=set(), your_invalid_target=None)),
        box,
    )

    _handle_message(serialize_message(OpponentDisconnectedMessage(grace_seconds=20)), box)

    assert box.state.opponent_disconnected_at is not None
    assert box.state.opponent_disconnect_grace_seconds == 20
    assert box.state.view_state == board  # the frozen board isn't lost, just carried forward
    assert box.state.color == WHITE


def test_handle_message_opponent_reconnected_clears_the_countdown_fields():
    box = ClientBox()
    _handle_message(serialize_message(MatchFoundMessage(color=WHITE)), box)
    _handle_message(serialize_message(OpponentDisconnectedMessage(grace_seconds=20)), box)

    _handle_message(serialize_message(OpponentReconnectedMessage()), box)

    assert box.state.opponent_disconnected_at is None
    assert box.state.opponent_disconnect_grace_seconds is None


def test_handle_message_state_carries_forward_the_disconnect_countdown_across_ticks():
    """The tick loop keeps broadcasting state while paused - each of
    those StateMessages must not silently clear an in-progress
    countdown started by an earlier OpponentDisconnectedMessage."""
    box = ClientBox()
    _handle_message(serialize_message(MatchFoundMessage(color=WHITE)), box)
    _handle_message(serialize_message(OpponentDisconnectedMessage(grace_seconds=20)), box)
    disconnected_at_before = box.state.opponent_disconnected_at

    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    _handle_message(
        serialize_message(StateMessage(board=board, your_selected_pos=None, your_legal_destinations=set(), your_invalid_target=None)),
        box,
    )

    assert box.state.opponent_disconnected_at == disconnected_at_before
    assert box.state.opponent_disconnect_grace_seconds == 20

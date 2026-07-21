from kungfu_chess.client.client_state import ClientState, _game_over_started_at, apply_message
from kungfu_chess.engine.board_view_state import BoardViewState
from kungfu_chess.model.piece import WHITE
from kungfu_chess.server.messages import (
    LoginFailedMessage,
    LoginOkMessage,
    MatchFoundMessage,
    NoOpponentFoundMessage,
    OpponentDisconnectedMessage,
    OpponentReconnectedMessage,
    StateMessage,
    WaitingForOpponentMessage,
)


def _match_found(color):
    return MatchFoundMessage(
        color=color, white_username="alice", white_rating=1200, black_username="bob", black_rating=1216,
    )


def test_game_over_started_at_is_none_while_the_game_is_still_playing():
    assert _game_over_started_at(previous=None, board_game_over=False) is None
    assert _game_over_started_at(previous=123.0, board_game_over=False) is None


def test_game_over_started_at_is_set_once_the_game_ends():
    result = _game_over_started_at(previous=None, board_game_over=True)
    assert result is not None


def test_game_over_started_at_keeps_the_original_timestamp_across_later_ticks():
    assert _game_over_started_at(previous=42.0, board_game_over=True) == 42.0


def test_apply_message_login_ok_stores_the_rating_and_moves_to_the_lobby():
    state = apply_message(LoginOkMessage(rating=1234), ClientState())

    assert state.phase == "lobby"  # waits here for the player to click Play, no auto-matchmaking
    assert state.rating == 1234


def test_apply_message_waiting_for_opponent_carries_forward_the_rating():
    state = apply_message(LoginOkMessage(rating=1234), ClientState())

    state = apply_message(WaitingForOpponentMessage(), state)

    assert state.phase == "waiting"
    assert state.rating == 1234


def test_apply_message_no_opponent_found_carries_forward_the_rating():
    state = apply_message(LoginOkMessage(rating=1234), ClientState())

    state = apply_message(NoOpponentFoundMessage(), state)

    assert state.phase == "no_opponent"
    assert state.rating == 1234


def test_apply_message_login_failed_sets_the_terminal_phase_and_reason():
    state = apply_message(LoginFailedMessage(reason="wrong password"), ClientState())

    assert state.phase == "login_failed"
    assert state.login_failure_reason == "wrong password"


def test_apply_message_match_found_sets_phase_color_and_matched_at():
    state = apply_message(_match_found(WHITE), ClientState())

    assert state.phase == "matched"
    assert state.color == WHITE
    assert state.matched_at is not None


def test_apply_message_match_found_stores_both_players_identity():
    state = apply_message(_match_found(WHITE), ClientState())

    assert state.white_player.username == "alice"
    assert state.white_player.rating == 1200
    assert state.black_player.username == "bob"
    assert state.black_player.rating == 1216


def test_apply_message_state_carries_forward_player_identity():
    state = apply_message(_match_found(WHITE), ClientState())

    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state_message = StateMessage(board=board, your_selected_pos=None, your_legal_destinations=set(), your_invalid_target=None)
    state = apply_message(state_message, state)

    assert state.white_player.username == "alice"
    assert state.black_player.username == "bob"


def test_apply_message_state_carries_forward_color_and_matched_at():
    state = apply_message(_match_found(WHITE), ClientState())
    matched_at_before = state.matched_at

    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state_message = StateMessage(board=board, your_selected_pos=None, your_legal_destinations=set(), your_invalid_target=None)
    state = apply_message(state_message, state)

    assert state.color == WHITE
    assert state.matched_at == matched_at_before
    assert state.view_state == board
    assert state.game_over_started_at is None


def test_apply_message_state_sets_game_over_started_at_once_the_game_ends():
    state = apply_message(_match_found(WHITE), ClientState())

    ended_board = BoardViewState(width=8, height=8, game_over=True, pieces=())
    state_message = StateMessage(board=ended_board, your_selected_pos=None, your_legal_destinations=set(), your_invalid_target=None)
    state = apply_message(state_message, state)

    assert state.game_over_started_at is not None


def test_apply_message_opponent_disconnected_sets_the_countdown_fields_without_losing_board_state():
    state = apply_message(_match_found(WHITE), ClientState())
    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state = apply_message(
        StateMessage(board=board, your_selected_pos=None, your_legal_destinations=set(), your_invalid_target=None), state
    )

    state = apply_message(OpponentDisconnectedMessage(grace_seconds=20), state)

    assert state.opponent_disconnected_at is not None
    assert state.opponent_disconnect_grace_seconds == 20
    assert state.view_state == board  # the frozen board isn't lost, just carried forward
    assert state.color == WHITE


def test_apply_message_opponent_reconnected_clears_the_countdown_fields():
    state = apply_message(_match_found(WHITE), ClientState())
    state = apply_message(OpponentDisconnectedMessage(grace_seconds=20), state)

    state = apply_message(OpponentReconnectedMessage(), state)

    assert state.opponent_disconnected_at is None
    assert state.opponent_disconnect_grace_seconds is None


def test_apply_message_state_carries_forward_the_disconnect_countdown_across_ticks():
    """The tick loop keeps broadcasting state while paused - each of
    those StateMessages must not silently clear an in-progress
    countdown started by an earlier OpponentDisconnectedMessage."""
    state = apply_message(_match_found(WHITE), ClientState())
    state = apply_message(OpponentDisconnectedMessage(grace_seconds=20), state)
    disconnected_at_before = state.opponent_disconnected_at

    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state = apply_message(
        StateMessage(board=board, your_selected_pos=None, your_legal_destinations=set(), your_invalid_target=None), state
    )

    assert state.opponent_disconnected_at == disconnected_at_before
    assert state.opponent_disconnect_grace_seconds == 20

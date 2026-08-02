from kungfu_chess.client.client_state import (
    CAPTURE_EVENT,
    GAME_OVER_EVENT,
    GAME_START_EVENT,
    INVALID_EVENT,
    MOVE_EVENT,
    SELECT_EVENT,
    ClientState,
    PendingMotion,
    _game_over_started_at,
    _prune_expired_motions,
    apply_message,
    events_since,
)
from kungfu_chess.engine.board_view_state import BoardViewState, MoveLogEntry
from kungfu_chess.model.piece import WHITE
from kungfu_chess.model.position import Position
from kungfu_chess.server.messages import (
    CreateRoomFailedMessage,
    JoinRoomFailedMessage,
    LoggedOutMessage,
    LoginFailedMessage,
    LoginOkMessage,
    MatchFoundMessage,
    NoOpponentFoundMessage,
    OpponentDisconnectedMessage,
    OpponentReconnectedMessage,
    LeftRoomMessage,
    PieceMotionStartedMessage,
    RoomCancelledMessage,
    RoomCreatedMessage,
    SeekCancelledMessage,
    SpectatingMessage,
    StateMessage,
    WaitingForOpponentMessage,
)


def _match_found(color, room_id=None):
    return MatchFoundMessage(
        color=color, white_username="alice", white_rating=1200, black_username="bob", black_rating=1216,
        room_id=room_id,
    )


def test_game_over_started_at_is_none_while_the_game_is_still_playing():
    assert _game_over_started_at(previous=None, board_game_over=False) is None
    assert _game_over_started_at(previous=123.0, board_game_over=False) is None


def test_game_over_started_at_is_set_once_the_game_ends():
    result = _game_over_started_at(previous=None, board_game_over=True)
    assert result is not None


def test_game_over_started_at_keeps_the_original_timestamp_across_later_ticks():
    assert _game_over_started_at(previous=42.0, board_game_over=True) == 42.0


def _pending_motion(started_at, duration_ms=500):
    return PendingMotion(
        from_position=Position(6, 0), to_position=Position(5, 0), duration_ms=duration_ms, started_at=started_at,
    )


def test_prune_expired_motions_drops_a_motion_whose_duration_has_elapsed():
    pending = {Position(6, 0): _pending_motion(started_at=0.0, duration_ms=500)}

    result = _prune_expired_motions(pending, now=1.0)  # 1000ms later, well past the 500ms duration

    assert result == {}


def test_prune_expired_motions_keeps_a_motion_still_in_flight():
    motion = _pending_motion(started_at=0.0, duration_ms=500)
    pending = {Position(6, 0): motion}

    result = _prune_expired_motions(pending, now=0.1)  # 100ms later, still short of the 500ms duration

    assert result == {Position(6, 0): motion}


def test_apply_message_login_ok_stores_the_rating_and_moves_to_the_lobby():
    state = apply_message(LoginOkMessage(rating=1234, username="efrat", token="a-jwt-token"), ClientState())

    assert state.phase == "lobby"  # waits here for the player to click Play, no auto-matchmaking
    assert state.rating == 1234
    assert state.auth_token == "a-jwt-token"  # saved to disk as a side effect elsewhere (network_transport.py), not here


def test_apply_message_logged_out_returns_to_a_fresh_login_entry():
    state = apply_message(LoginOkMessage(rating=1234, username="efrat", token="a-jwt-token"), ClientState())

    state = apply_message(LoggedOutMessage(), state)

    assert state.phase == "login_entry"
    assert state.auth_token is None
    assert state.saved_username is None  # a revoked token must not still offer "Continue as X"


def test_apply_message_waiting_for_opponent_carries_forward_the_rating():
    state = apply_message(LoginOkMessage(rating=1234, username="efrat", token="a-jwt-token"), ClientState())

    state = apply_message(WaitingForOpponentMessage(), state)

    assert state.phase == "waiting"
    assert state.rating == 1234


def test_apply_message_no_opponent_found_carries_forward_the_rating():
    state = apply_message(LoginOkMessage(rating=1234, username="efrat", token="a-jwt-token"), ClientState())

    state = apply_message(NoOpponentFoundMessage(), state)

    assert state.phase == "no_opponent"
    assert state.rating == 1234


def test_apply_message_login_failed_returns_to_login_entry_with_the_reason():
    state = apply_message(
        LoginFailedMessage(reason="wrong password"),
        ClientState(login_username_value="efrat", login_password_value="hunter2"),
    )

    assert state.phase == "login_entry"
    assert state.login_failure_reason == "wrong password"
    assert state.login_username_value == "efrat"  # kept - no need to retype it
    assert state.login_password_value == ""  # cleared - never keep a rejected password around


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


def test_apply_message_state_is_ignored_outside_matched_or_spectating():
    """A StateMessage arriving while on the room_create_entry screen (a
    stray broadcast from a GameRoom this client already left behind,
    e.g. via LeaveRoomMessage - see Matchmaker._leave_room) must not
    silently wipe out local-only fields like text_entry_value that
    aren't part of the message at all."""
    state = ClientState(phase="room_create_entry", text_entry_value="efrat-ro")

    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state_message = StateMessage(board=board, your_selected_pos=None, your_legal_destinations=set(), your_invalid_target=None)
    result = apply_message(state_message, state)

    assert result is state
    assert result.text_entry_value == "efrat-ro"


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


def test_apply_message_piece_motion_started_records_a_pending_motion():
    state = apply_message(_match_found(WHITE), ClientState())

    state = apply_message(
        PieceMotionStartedMessage(from_position=Position(6, 0), to_position=Position(5, 0), duration_ms=500), state
    )

    motion = state.pending_motions[Position(6, 0)]
    assert motion.to_position == Position(5, 0)
    assert motion.duration_ms == 500


def test_apply_message_state_carries_forward_an_active_pending_motion():
    state = apply_message(_match_found(WHITE), ClientState())
    state = apply_message(
        PieceMotionStartedMessage(from_position=Position(6, 0), to_position=Position(5, 0), duration_ms=60_000), state
    )

    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state_message = StateMessage(board=board, your_selected_pos=None, your_legal_destinations=set(), your_invalid_target=None)
    state = apply_message(state_message, state)

    assert Position(6, 0) in state.pending_motions  # a 60s duration can't have elapsed yet


def test_apply_message_state_drops_a_pending_motion_once_it_expires():
    state = apply_message(_match_found(WHITE), ClientState())
    # duration_ms=0 - already "expired" the instant it's recorded, well before the next StateMessage arrives
    state = apply_message(
        PieceMotionStartedMessage(from_position=Position(6, 0), to_position=Position(5, 0), duration_ms=0), state
    )

    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state_message = StateMessage(board=board, your_selected_pos=None, your_legal_destinations=set(), your_invalid_target=None)
    state = apply_message(state_message, state)

    assert state.pending_motions == {}


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


def test_apply_message_match_found_carries_the_room_id():
    state = apply_message(_match_found(WHITE, room_id="ABC123"), ClientState())

    assert state.room_id == "ABC123"


def test_apply_message_match_found_room_id_defaults_to_none_for_a_play_matched_game():
    state = apply_message(_match_found(WHITE), ClientState())

    assert state.room_id is None


def test_apply_message_room_created_sets_phase_and_room_id():
    state = apply_message(LoginOkMessage(rating=1234, username="efrat", token="a-jwt-token"), ClientState())

    state = apply_message(RoomCreatedMessage(room_id="ABC123"), state)

    assert state.phase == "room_waiting"
    assert state.room_id == "ABC123"
    assert state.rating == 1234


def test_apply_message_join_room_failed_shows_the_reason():
    state = apply_message(LoginOkMessage(rating=1234, username="efrat", token="a-jwt-token"), ClientState())

    state = apply_message(JoinRoomFailedMessage(reason="room_not_found"), state)

    assert state.phase == "room_action_failed"
    assert state.room_action_failure_reason == "room_not_found"
    assert state.room_action_failure_kind == "join"
    assert state.rating == 1234


def test_apply_message_create_room_failed_shows_the_reason_and_kind():
    state = apply_message(LoginOkMessage(rating=1234, username="efrat", token="a-jwt-token"), ClientState())

    state = apply_message(CreateRoomFailedMessage(reason="room_name_taken"), state)

    assert state.phase == "room_action_failed"
    assert state.room_action_failure_reason == "room_name_taken"
    assert state.room_action_failure_kind == "create"
    assert state.rating == 1234


def test_apply_message_room_cancelled_returns_to_the_lobby():
    state = apply_message(RoomCreatedMessage(room_id="ABC123"), ClientState(rating=1234))

    state = apply_message(RoomCancelledMessage(), state)

    assert state.phase == "lobby"


def test_apply_message_seek_cancelled_returns_to_the_lobby():
    state = apply_message(WaitingForOpponentMessage(), ClientState(rating=1234))

    state = apply_message(SeekCancelledMessage(), state)

    assert state.phase == "lobby"
    assert state.rating == 1234


def test_apply_message_left_room_returns_to_the_lobby():
    state = apply_message(_match_found(WHITE), ClientState(rating=1234))

    state = apply_message(LeftRoomMessage(), state)

    assert state.phase == "lobby"
    assert state.rating == 1234


def test_apply_message_match_found_carries_forward_the_rating():
    state = apply_message(_match_found(WHITE), ClientState(rating=1234))

    assert state.rating == 1234


def test_apply_message_spectating_sets_phase_color_none_and_both_players():
    state = apply_message(
        SpectatingMessage(room_id="ABC123", white_username="alice", white_rating=1200, black_username="bob", black_rating=1216),
        ClientState(),
    )

    assert state.phase == "spectating"
    assert state.color is None
    assert state.room_id == "ABC123"
    assert state.white_player.username == "alice"
    assert state.black_player.username == "bob"


def test_apply_message_spectating_does_not_start_a_starting_countdown():
    """A spectator isn't about to move anything - it should see the
    live board immediately, not the "starting in N..." countdown a
    real player gets on match_found."""
    state = apply_message(
        SpectatingMessage(room_id="ABC123", white_username="alice", white_rating=1200, black_username="bob", black_rating=1216),
        ClientState(),
    )

    assert state.matched_at is None


def test_apply_message_state_carries_forward_the_room_id_across_ticks():
    state = apply_message(_match_found(WHITE, room_id="ABC123"), ClientState())

    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state = apply_message(
        StateMessage(board=board, your_selected_pos=None, your_legal_destinations=set(), your_invalid_target=None), state
    )

    assert state.room_id == "ABC123"


def test_apply_message_state_preserves_the_spectating_phase_across_ticks():
    state = apply_message(
        SpectatingMessage(room_id="ABC123", white_username="alice", white_rating=1200, black_username="bob", black_rating=1216),
        ClientState(),
    )

    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state = apply_message(
        StateMessage(board=board, your_selected_pos=None, your_legal_destinations=set(), your_invalid_target=None), state
    )

    assert state.phase == "spectating"
    assert state.color is None


# ==========================================
# events_since (sound-effect triggers)
# ==========================================

def _quiet_move(elapsed_ms=0):
    return MoveLogEntry(elapsed_ms=elapsed_ms, from_pos=Position(6, 4), to_pos=Position(4, 4), kind="pawn", is_capture=False)


def _capture_move(elapsed_ms=0):
    return MoveLogEntry(elapsed_ms=elapsed_ms, from_pos=Position(4, 4), to_pos=Position(3, 3), kind="pawn", is_capture=True)


def test_events_since_detects_game_start_on_match_found():
    old_state = ClientState()
    new_state = apply_message(_match_found(WHITE), old_state)

    assert GAME_START_EVENT in events_since(old_state, new_state)


def test_events_since_does_not_refire_game_start_across_later_ticks():
    old_state = apply_message(_match_found(WHITE), ClientState())
    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    new_state = apply_message(
        StateMessage(board=board, your_selected_pos=None, your_legal_destinations=set(), your_invalid_target=None), old_state
    )

    assert GAME_START_EVENT not in events_since(old_state, new_state)


def test_events_since_detects_a_new_quiet_move():
    board_before = BoardViewState(width=8, height=8, game_over=False, pieces=(), move_log={WHITE: ()})
    board_after = BoardViewState(width=8, height=8, game_over=False, pieces=(), move_log={WHITE: (_quiet_move(),)})
    old_state = ClientState(view_state=board_before)
    new_state = ClientState(view_state=board_after)

    events = events_since(old_state, new_state)
    assert MOVE_EVENT in events
    assert CAPTURE_EVENT not in events


def test_events_since_detects_a_new_capture():
    board_before = BoardViewState(width=8, height=8, game_over=False, pieces=(), move_log={WHITE: ()})
    board_after = BoardViewState(width=8, height=8, game_over=False, pieces=(), move_log={WHITE: (_capture_move(),)})
    old_state = ClientState(view_state=board_before)
    new_state = ClientState(view_state=board_after)

    assert CAPTURE_EVENT in events_since(old_state, new_state)


def test_events_since_detects_game_over_transition():
    board_before = BoardViewState(width=8, height=8, game_over=False, pieces=())
    board_after = BoardViewState(width=8, height=8, game_over=True, pieces=())
    old_state = ClientState(view_state=board_before)
    new_state = ClientState(view_state=board_after)

    assert GAME_OVER_EVENT in events_since(old_state, new_state)


def test_events_since_skips_move_detection_on_the_first_snapshot():
    """Right after match-found or a reconnect, old_state.view_state is
    None - the first StateMessage that follows must be treated as a
    baseline, not replayed as a burst of move/capture events for
    however much move-log history the game already had."""
    board_with_history = BoardViewState(
        width=8, height=8, game_over=False, pieces=(), move_log={WHITE: (_quiet_move(), _capture_move())},
    )
    old_state = ClientState(view_state=None)
    new_state = ClientState(view_state=board_with_history)

    assert events_since(old_state, new_state) == frozenset()


def test_events_since_returns_empty_when_nothing_changed():
    board = BoardViewState(width=8, height=8, game_over=False, pieces=(), move_log={WHITE: (_quiet_move(),)})
    state = ClientState(view_state=board)

    assert events_since(state, state) == frozenset()


def test_events_since_detects_a_new_selection():
    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    old_state = ClientState(view_state=board, selected_pos=None)
    new_state = ClientState(view_state=board, selected_pos=Position(6, 4))

    assert SELECT_EVENT in events_since(old_state, new_state)


def test_events_since_does_not_refire_select_while_the_same_cell_stays_selected():
    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state = ClientState(view_state=board, selected_pos=Position(6, 4))

    assert SELECT_EVENT not in events_since(state, state)


def test_events_since_detects_a_new_invalid_target():
    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    old_state = ClientState(view_state=board, invalid_target=None)
    new_state = ClientState(view_state=board, invalid_target=Position(3, 3))

    assert INVALID_EVENT in events_since(old_state, new_state)


def test_events_since_skips_select_and_invalid_detection_on_the_first_snapshot():
    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    old_state = ClientState(view_state=None)
    new_state = ClientState(view_state=board, selected_pos=Position(6, 4), invalid_target=Position(3, 3))

    events = events_since(old_state, new_state)
    assert SELECT_EVENT not in events
    assert INVALID_EVENT not in events

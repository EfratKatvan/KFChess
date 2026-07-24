import time

from kungfu_chess.client.client_state import ClientState
from kungfu_chess.client.input_controller import (
    CREATE_ROOM_BUTTON_CLICKED,
    JOIN_ROOM_BUTTON_CLICKED,
    LOGIN_FIELD_PASSWORD_CLICKED,
    LOGIN_FIELD_USERNAME_CLICKED,
    SKIN_PIECES1_SELECTED,
    SKIN_PIECES2_SELECTED,
    SKIN_PIECES3_SELECTED,
    TEXT_ENTRY_CANCEL_CLICKED,
    apply_key_press,
    decide_message,
)
from kungfu_chess.engine.board_view_state import BoardViewState
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.model.board import Board
from kungfu_chess.model.position import Position
from kungfu_chess.server import protocol
from kungfu_chess.server.messages import (
    CancelRoomMessage,
    CancelSeekMessage,
    CreateRoomMessage,
    JoinRoomMessage,
    JumpMessage,
    LeaveRoomMessage,
    LoginMessage,
    RegisterMessage,
    ResignMessage,
    RestartMessage,
    SeekGameMessage,
    SelectOrMoveMessage,
)
from kungfu_chess.view import image_view
from kungfu_chess.view.network_presentation import (
    TOP_BANNER_HEIGHT,
    create_room_button_rect,
    join_room_button_rect,
    login_button_rect,
    login_password_field_rect,
    login_username_field_rect,
    play_button_rect,
    register_button_rect,
    resign_button_rect,
    room_pending_cancel_button_rect,
    skin_pieces1_button_rect,
    skin_pieces2_button_rect,
    skin_pieces3_button_rect,
    text_entry_cancel_button_rect,
)
from kungfu_chess.view.renderer import game_over_back_to_lobby_button_rect, game_over_button_rect

CELL_SIZE = 100
SCREEN_WIDTH, SCREEN_HEIGHT = 800, 800


def _mapper():
    return BoardMapper(Board(width=8, height=8), cell_size=CELL_SIZE, y_offset=TOP_BANNER_HEIGHT)


def _decide(state, is_left_click=False, is_right_click=False, x=0, y=0, mapper=None):
    return decide_message(
        state, is_left_click, is_right_click, x, y,
        mapper or _mapper(), CELL_SIZE, SCREEN_WIDTH, SCREEN_HEIGHT,
    )


# ==========================================
# Skin menu
# ==========================================

def test_skin_menu_click_on_each_button_returns_its_own_sentinel():
    state = ClientState(phase="skin_menu")
    for rect_fn, sentinel in (
        (skin_pieces1_button_rect, SKIN_PIECES1_SELECTED),
        (skin_pieces2_button_rect, SKIN_PIECES2_SELECTED),
        (skin_pieces3_button_rect, SKIN_PIECES3_SELECTED),
    ):
        x, y, w, h = rect_fn(SCREEN_WIDTH, SCREEN_HEIGHT)
        assert _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2) == sentinel


def test_skin_menu_click_elsewhere_sends_nothing():
    state = ClientState(phase="skin_menu")

    assert _decide(state, is_left_click=True, x=0, y=0) is None


# ==========================================
# Login screen
# ==========================================

def test_login_click_on_username_field_returns_the_focus_sentinel():
    state = ClientState(phase="login_entry")
    x, y, w, h = login_username_field_rect(SCREEN_WIDTH, SCREEN_HEIGHT)

    assert _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2) == LOGIN_FIELD_USERNAME_CLICKED


def test_login_click_on_password_field_returns_the_focus_sentinel():
    state = ClientState(phase="login_entry")
    x, y, w, h = login_password_field_rect(SCREEN_WIDTH, SCREEN_HEIGHT)

    assert _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2) == LOGIN_FIELD_PASSWORD_CLICKED


def test_login_button_click_with_both_fields_filled_sends_login_message():
    state = ClientState(phase="login_entry", login_username_value="efrat", login_password_value="hunter2")
    x, y, w, h = login_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)

    message = _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2)

    assert message == LoginMessage(username="efrat", password="hunter2")


def test_register_button_click_with_both_fields_filled_sends_register_message():
    state = ClientState(phase="login_entry", login_username_value="efrat", login_password_value="hunter2")
    x, y, w, h = register_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)

    message = _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2)

    assert message == RegisterMessage(username="efrat", password="hunter2")


def test_login_button_click_with_an_empty_field_sends_nothing():
    state = ClientState(phase="login_entry", login_username_value="efrat", login_password_value="")
    x, y, w, h = login_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)

    assert _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2) is None


def test_typing_into_the_active_login_field_appends_to_it():
    state = ClientState(phase="login_entry", login_active_field="username")

    new_state, message = apply_key_press(ord("e"), state)

    assert new_state.login_username_value == "e"
    assert new_state.login_password_value == ""
    assert message is None


def test_typing_goes_to_the_password_field_once_it_is_active():
    state = ClientState(phase="login_entry", login_active_field="password", login_username_value="efrat")

    new_state, message = apply_key_press(ord("h"), state)

    assert new_state.login_username_value == "efrat"
    assert new_state.login_password_value == "h"
    assert message is None


def test_tab_switches_the_active_login_field():
    state = ClientState(phase="login_entry", login_active_field="username")

    new_state, _ = apply_key_press(9, state)
    assert new_state.login_active_field == "password"

    new_state_again, _ = apply_key_press(9, new_state)
    assert new_state_again.login_active_field == "username"


def test_backspace_removes_from_the_active_login_field():
    state = ClientState(phase="login_entry", login_active_field="username", login_username_value="efrat")

    new_state, message = apply_key_press(8, state)

    assert new_state.login_username_value == "efra"
    assert message is None


def test_enter_with_both_login_fields_filled_submits_a_login_message():
    state = ClientState(phase="login_entry", login_username_value="efrat", login_password_value="hunter2")

    new_state, message = apply_key_press(13, state)

    assert new_state is state  # apply_key_press doesn't transition phase itself - run_client's _dispatch does, on submit
    assert message == LoginMessage(username="efrat", password="hunter2")


def test_enter_with_an_empty_login_field_sends_nothing():
    state = ClientState(phase="login_entry", login_username_value="efrat", login_password_value="")

    new_state, message = apply_key_press(13, state)

    assert message is None


def test_escape_on_the_login_screen_leaves_state_untouched():
    """Unlike the room text-entry phases, Escape here isn't consumed to
    cancel back to anything - there's nothing before the login screen,
    so it must fall through to run_client's own "close the window"."""
    state = ClientState(phase="login_entry", login_username_value="efrat")

    new_state, message = apply_key_press(image_view.ESC_KEY, state)

    assert new_state is state
    assert message is None


def test_lobby_click_inside_play_button_sends_seek_game():
    x, y, w, h = play_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)
    state = ClientState(phase="lobby")

    message = _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2)

    assert isinstance(message, SeekGameMessage)


def test_lobby_click_outside_play_button_sends_nothing():
    state = ClientState(phase="lobby")

    assert _decide(state, is_left_click=True, x=0, y=0) is None


def test_no_opponent_phase_also_accepts_the_play_button():
    x, y, w, h = play_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)
    state = ClientState(phase="no_opponent")

    message = _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2)

    assert isinstance(message, SeekGameMessage)


def test_click_before_matched_sends_nothing():
    state = ClientState(phase="waiting")

    assert _decide(state, is_left_click=True, x=150, y=150) is None


def test_waiting_click_on_back_button_sends_cancel_seek():
    x, y, w, h = room_pending_cancel_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)
    state = ClientState(phase="waiting")

    message = _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2)

    assert isinstance(message, CancelSeekMessage)


def test_click_during_the_starting_countdown_is_ignored():
    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state = ClientState(phase="matched", view_state=board, matched_at=time.perf_counter())

    assert _decide(state, is_left_click=True, x=150, y=150 + TOP_BANNER_HEIGHT) is None


def test_click_while_opponent_is_disconnected_is_ignored():
    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state = ClientState(
        phase="matched", view_state=board, matched_at=0.0,
        opponent_disconnected_at=time.perf_counter(), opponent_disconnect_grace_seconds=20,
    )

    assert _decide(state, is_left_click=True, x=150, y=150 + TOP_BANNER_HEIGHT) is None


def test_click_on_the_resign_button_sends_resign():
    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state = ClientState(phase="matched", view_state=board, matched_at=0.0)
    x, y, w, h = resign_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)

    message = _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2)

    assert isinstance(message, ResignMessage)


def test_resign_button_does_nothing_after_game_over():
    board = BoardViewState(width=8, height=8, game_over=True, pieces=())
    state = ClientState(phase="matched", view_state=board, matched_at=0.0)
    x, y, w, h = resign_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)

    # same spot, but the button isn't shown anymore once the game has ended
    message = _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2)

    assert not isinstance(message, ResignMessage)


def test_left_click_on_a_cell_sends_select_or_move():
    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state = ClientState(phase="matched", view_state=board, matched_at=0.0)

    message = _decide(state, is_left_click=True, x=50, y=50 + TOP_BANNER_HEIGHT)

    assert message == SelectOrMoveMessage(row=0, col=0)


def test_right_click_on_a_cell_sends_jump():
    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state = ClientState(phase="matched", view_state=board, matched_at=0.0)

    message = _decide(state, is_right_click=True, x=50, y=50 + TOP_BANNER_HEIGHT)

    assert message == JumpMessage(row=0, col=0)


def test_click_outside_the_board_bounds_sends_nothing():
    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state = ClientState(phase="matched", view_state=board, matched_at=0.0)

    assert _decide(state, is_left_click=True, x=-50, y=50 + TOP_BANNER_HEIGHT) is None


def test_click_on_the_restart_button_after_game_over_sends_restart():
    board = BoardViewState(width=8, height=8, game_over=True, pieces=())
    state = ClientState(phase="matched", view_state=board, matched_at=0.0)
    x, y, w, h = game_over_button_rect(8, 8, CELL_SIZE)

    message = _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2 + TOP_BANNER_HEIGHT)

    assert isinstance(message, RestartMessage)


def test_click_on_the_back_to_lobby_button_after_game_over_sends_leave_room():
    board = BoardViewState(width=8, height=8, game_over=True, pieces=())
    state = ClientState(phase="matched", view_state=board, matched_at=0.0)
    x, y, w, h = game_over_back_to_lobby_button_rect(8, 8, CELL_SIZE)

    message = _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2 + TOP_BANNER_HEIGHT)

    assert isinstance(message, LeaveRoomMessage)


def test_back_to_lobby_button_does_nothing_before_game_over():
    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state = ClientState(phase="matched", view_state=board, matched_at=0.0)
    x, y, w, h = game_over_back_to_lobby_button_rect(8, 8, CELL_SIZE)

    # the same click, while the board is still live, falls into ordinary cell selection instead
    message = _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2 + TOP_BANNER_HEIGHT)

    assert not isinstance(message, LeaveRoomMessage)


def test_click_elsewhere_after_game_over_sends_nothing():
    board = BoardViewState(width=8, height=8, game_over=True, pieces=())
    state = ClientState(phase="matched", view_state=board, matched_at=0.0)

    assert _decide(state, is_left_click=True, x=0, y=TOP_BANNER_HEIGHT) is None


# ==========================================
# Lobby: Create Room / Join Room buttons
# ==========================================

def test_lobby_click_inside_create_room_button_returns_the_sentinel():
    x, y, w, h = create_room_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)
    state = ClientState(phase="lobby")

    message = _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2)

    assert message == CREATE_ROOM_BUTTON_CLICKED


def test_lobby_click_inside_join_room_button_returns_the_sentinel():
    x, y, w, h = join_room_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)
    state = ClientState(phase="lobby")

    message = _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2)

    assert message == JOIN_ROOM_BUTTON_CLICKED


def test_no_opponent_phase_also_accepts_both_room_buttons():
    state = ClientState(phase="no_opponent")

    cx, cy, cw, ch = create_room_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)
    assert _decide(state, is_left_click=True, x=cx + cw // 2, y=cy + ch // 2) == CREATE_ROOM_BUTTON_CLICKED

    jx, jy, jw, jh = join_room_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)
    assert _decide(state, is_left_click=True, x=jx + jw // 2, y=jy + jh // 2) == JOIN_ROOM_BUTTON_CLICKED


def test_room_action_failed_phase_also_accepts_play_create_and_join_buttons():
    state = ClientState(phase="room_action_failed", room_action_failure_reason="room_not_found", room_action_failure_kind="join")

    play_x, play_y, play_w, play_h = play_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)
    assert isinstance(_decide(state, is_left_click=True, x=play_x + play_w // 2, y=play_y + play_h // 2), SeekGameMessage)

    cx, cy, cw, ch = create_room_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)
    assert _decide(state, is_left_click=True, x=cx + cw // 2, y=cy + ch // 2) == CREATE_ROOM_BUTTON_CLICKED

    jx, jy, jw, jh = join_room_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)
    assert _decide(state, is_left_click=True, x=jx + jw // 2, y=jy + jh // 2) == JOIN_ROOM_BUTTON_CLICKED


# ==========================================
# Text entry (Create/Join Room) and room-pending Cancel
# ==========================================

def test_text_entry_click_on_cancel_button_returns_the_sentinel():
    x, y, w, h = text_entry_cancel_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)

    for phase in ("room_create_entry", "room_join_entry"):
        state = ClientState(phase=phase)
        assert _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2) == TEXT_ENTRY_CANCEL_CLICKED


def test_text_entry_click_elsewhere_sends_nothing():
    state = ClientState(phase="room_create_entry")

    assert _decide(state, is_left_click=True, x=0, y=0) is None


def test_room_waiting_click_on_cancel_button_sends_cancel_room():
    x, y, w, h = room_pending_cancel_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)
    state = ClientState(phase="room_waiting", room_id="efrat-room")

    message = _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2)

    assert isinstance(message, CancelRoomMessage)


def test_room_waiting_phase_never_produces_a_click_message_elsewhere():
    state = ClientState(phase="room_waiting", room_id="efrat-room")

    assert _decide(state, is_left_click=True, x=50, y=50 + TOP_BANNER_HEIGHT) is None
    assert _decide(state, is_right_click=True, x=50, y=50 + TOP_BANNER_HEIGHT) is None


def test_spectating_phase_never_produces_a_click_message():
    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state = ClientState(phase="spectating", color=None, view_state=board)

    assert _decide(state, is_left_click=True, x=50, y=50 + TOP_BANNER_HEIGHT) is None
    assert _decide(state, is_right_click=True, x=50, y=50 + TOP_BANNER_HEIGHT) is None


# ==========================================
# apply_key_press
# ==========================================

def test_typing_a_printable_char_appends_to_the_buffer():
    for phase in ("room_create_entry", "room_join_entry"):
        state = ClientState(phase=phase, text_entry_value="efrat")
        new_state, message = apply_key_press(ord("!"), state)
        assert new_state.text_entry_value == "efrat!"
        assert message is None


def test_backspace_removes_the_last_character():
    state = ClientState(phase="room_create_entry", text_entry_value="efrat")

    new_state, message = apply_key_press(8, state)

    assert new_state.text_entry_value == "efra"
    assert message is None


def test_backspace_on_an_empty_buffer_is_a_no_op():
    state = ClientState(phase="room_create_entry", text_entry_value="")

    new_state, message = apply_key_press(8, state)

    assert new_state.text_entry_value == ""
    assert message is None


def test_enter_with_an_empty_buffer_is_a_no_op():
    state = ClientState(phase="room_create_entry", text_entry_value="")

    new_state, message = apply_key_press(13, state)

    assert new_state is state
    assert message is None


def test_enter_with_a_whitespace_only_buffer_is_a_no_op():
    state = ClientState(phase="room_join_entry", text_entry_value="   ")

    new_state, message = apply_key_press(13, state)

    assert new_state is state
    assert message is None


def test_enter_in_create_entry_sends_create_room_and_moves_to_pending_ack():
    state = ClientState(phase="room_create_entry", text_entry_value="efrat-room", rating=1200)

    new_state, message = apply_key_press(13, state)

    assert new_state.phase == "room_pending_ack"
    assert new_state.pending_room_action == "create"
    assert new_state.rating == 1200
    assert message == CreateRoomMessage(room_id="efrat-room")


def test_enter_in_join_entry_sends_join_room_and_moves_to_pending_ack():
    state = ClientState(phase="room_join_entry", text_entry_value="efrat-room")

    new_state, message = apply_key_press(13, state)

    assert new_state.phase == "room_pending_ack"
    assert new_state.pending_room_action == "join"
    assert message == JoinRoomMessage(room_id="efrat-room")


def test_enter_strips_surrounding_whitespace_from_the_typed_value():
    state = ClientState(phase="room_create_entry", text_entry_value="  efrat-room  ")

    _, message = apply_key_press(13, state)

    assert message == CreateRoomMessage(room_id="efrat-room")


def test_alternate_enter_key_code_also_works():
    state = ClientState(phase="room_create_entry", text_entry_value="efrat-room")

    _, message = apply_key_press(10, state)

    assert message == CreateRoomMessage(room_id="efrat-room")


def test_escape_cancels_entry_and_returns_to_the_lobby():
    state = ClientState(phase="room_create_entry", text_entry_value="efrat-room", rating=1200)

    new_state, message = apply_key_press(image_view.ESC_KEY, state)

    assert new_state.phase == "lobby"
    assert new_state.text_entry_value == ""
    assert new_state.rating == 1200
    assert message is None


def test_keys_are_ignored_outside_text_entry_phases():
    for phase in ("lobby", "matched", "room_waiting", "spectating"):
        state = ClientState(phase=phase)
        new_state, message = apply_key_press(ord("a"), state)
        assert new_state is state
        assert message is None


def test_irrelevant_key_codes_are_ignored_inside_text_entry():
    state = ClientState(phase="room_create_entry", text_entry_value="efrat")

    for key in (-1, 255, 0x250000):  # no key this frame, and a typical arrow-key code
        new_state, message = apply_key_press(key, state)
        assert new_state is state
        assert message is None


def test_typing_stops_appending_once_the_max_length_is_reached():
    max_length_value = "x" * protocol.MAX_ROOM_ID_LENGTH
    state = ClientState(phase="room_create_entry", text_entry_value=max_length_value)

    new_state, message = apply_key_press(ord("y"), state)

    assert new_state.text_entry_value == max_length_value  # unchanged - already at the cap
    assert message is None

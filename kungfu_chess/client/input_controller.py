from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, Optional, Tuple

from kungfu_chess.client.client_state import ClientState
from kungfu_chess.input.board_mapper import BoardMapper
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
    STARTING_DURATION_S,
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

"""The client's Application layer: turns a raw click or keystroke into
an outgoing protocol message (or nothing). Knows the game's
interaction rules - what's clickable/typeable in which phase - but
nothing about cv2, sockets, or pixels beyond hit-testing rects it's
handed. run_client is the only caller; it owns the actual cv2 event
dispatch and the network_transport.send() call. Already imports from
view/ for button rects (same as it always has), so importing
image_view.ESC_KEY here too isn't a new layering exception."""

# Local-only sentinels for the lobby's Create/Join Room buttons and the
# text-entry Cancel button - never sent over the wire (they don't
# belong in server/messages.py). run_client recognizes these and
# writes a local ClientState transition directly, rather than
# decide_message doing that I/O itself.
CREATE_ROOM_BUTTON_CLICKED = "__create_room_button_clicked__"
JOIN_ROOM_BUTTON_CLICKED = "__join_room_button_clicked__"
TEXT_ENTRY_CANCEL_CLICKED = "__text_entry_cancel_clicked__"

# Skin-menu selections - purely local (see network_presentation.py's
# skin_menu_screen docstring); run_client applies the choice to its own
# piece_set variable and moves on to the login screen.
SKIN_PIECES1_SELECTED = "__skin_pieces1_selected__"
SKIN_PIECES2_SELECTED = "__skin_pieces2_selected__"
SKIN_PIECES3_SELECTED = "__skin_pieces3_selected__"

# Login-screen field focus - local, just switches which field further
# keystrokes go to (ClientState.login_active_field).
LOGIN_FIELD_USERNAME_CLICKED = "__login_field_username_clicked__"
LOGIN_FIELD_PASSWORD_CLICKED = "__login_field_password_clicked__"

_ENTER_KEYS = (13, 10)
_BACKSPACE_KEY = 8
_TAB_KEY = 9
_TEXT_ENTRY_PHASES = ("room_create_entry", "room_join_entry")
_MAX_LOGIN_FIELD_LENGTH = 32


def decide_message(
    state: ClientState,
    is_left_click: bool,
    is_right_click: bool,
    x: int,
    y: int,
    mapper: BoardMapper,
    cell_size: int,
    screen_width: int,
    screen_height: int,
) -> Optional[Any]:
    """Pure decision: given the current state and one click, what
    message (if any) should be sent to the server. Returns None for
    clicks that mean nothing right now (wrong phase, still in the
    starting countdown, opponent disconnected, empty cell, ...)."""
    if state.phase == "skin_menu":
        if is_left_click and _point_in_rect(x, y, skin_pieces1_button_rect(screen_width, screen_height)):
            return SKIN_PIECES1_SELECTED
        if is_left_click and _point_in_rect(x, y, skin_pieces2_button_rect(screen_width, screen_height)):
            return SKIN_PIECES2_SELECTED
        if is_left_click and _point_in_rect(x, y, skin_pieces3_button_rect(screen_width, screen_height)):
            return SKIN_PIECES3_SELECTED
        return None
    if state.phase == "login_entry":
        if not is_left_click:
            return None
        if _point_in_rect(x, y, login_username_field_rect(screen_width, screen_height)):
            return LOGIN_FIELD_USERNAME_CLICKED
        if _point_in_rect(x, y, login_password_field_rect(screen_width, screen_height)):
            return LOGIN_FIELD_PASSWORD_CLICKED
        if _point_in_rect(x, y, login_button_rect(screen_width, screen_height)):
            return _build_login_message(state, LoginMessage)
        if _point_in_rect(x, y, register_button_rect(screen_width, screen_height)):
            return _build_login_message(state, RegisterMessage)
        return None
    if state.phase in ("lobby", "no_opponent", "room_action_failed"):
        if is_left_click and _point_in_rect(x, y, play_button_rect(screen_width, screen_height)):
            return SeekGameMessage()
        if is_left_click and _point_in_rect(x, y, create_room_button_rect(screen_width, screen_height)):
            return CREATE_ROOM_BUTTON_CLICKED
        if is_left_click and _point_in_rect(x, y, join_room_button_rect(screen_width, screen_height)):
            return JOIN_ROOM_BUTTON_CLICKED
        return None
    if state.phase in _TEXT_ENTRY_PHASES:
        if is_left_click and _point_in_rect(x, y, text_entry_cancel_button_rect(screen_width, screen_height)):
            return TEXT_ENTRY_CANCEL_CLICKED
        return None
    if state.phase == "room_waiting":
        if is_left_click and _point_in_rect(x, y, room_pending_cancel_button_rect(screen_width, screen_height)):
            return CancelRoomMessage()
        return None
    if state.phase == "waiting":
        if is_left_click and _point_in_rect(x, y, room_pending_cancel_button_rect(screen_width, screen_height)):
            return CancelSeekMessage()
        return None
    if state.phase != "matched" or state.view_state is None:
        return None
    if state.matched_at is not None and time.perf_counter() - state.matched_at < STARTING_DURATION_S:
        return None  # still in the starting countdown - no board is shown yet, ignore clicks
    if state.opponent_disconnected_at is not None:
        return None  # opponent is disconnected - the countdown screen is shown instead of the board

    if is_left_click:
        view_state = state.view_state
        # The Resign button lives in the top banner - whole-window
        # coordinates, unlike the board/game-over-overlay checks below
        # which subtract TOP_BANNER_HEIGHT first.
        if not view_state.game_over and _point_in_rect(x, y, resign_button_rect(screen_width, screen_height)):
            return ResignMessage()
        if view_state.game_over:
            button_rect = game_over_button_rect(view_state.width, view_state.height, cell_size)
            if _point_in_rect(x, y - TOP_BANNER_HEIGHT, button_rect):
                return RestartMessage()
            back_to_lobby_rect = game_over_back_to_lobby_button_rect(view_state.width, view_state.height, cell_size)
            if _point_in_rect(x, y - TOP_BANNER_HEIGHT, back_to_lobby_rect):
                return LeaveRoomMessage()
            return None
        cell = mapper.to_cell(x, y)
        if cell is not None:
            return SelectOrMoveMessage(row=cell.row, col=cell.col)
        return None
    if is_right_click:
        cell = mapper.to_cell(x, y)
        if cell is not None:
            return JumpMessage(row=cell.row, col=cell.col)
        return None
    return None


def apply_key_press(key: int, state: ClientState) -> Tuple[ClientState, Optional[Any]]:
    """Pure: one cv2 key code (as returned by Img.show(), already
    masked to its low byte there - see its own docstring for why) plus
    the current state -> (new state, message to send or None). A no-op
    for every phase except the login screen and the two room-name
    text-entry ones, mirroring decide_message's own phase gating."""
    if state.phase == "login_entry":
        return _apply_login_key_press(key, state)
    if state.phase not in _TEXT_ENTRY_PHASES:
        return state, None
    if key == image_view.ESC_KEY:
        return ClientState(phase="lobby", rating=state.rating), None
    if key in _ENTER_KEYS:
        value = state.text_entry_value.strip()
        if not value:
            return state, None
        kind = "create" if state.phase == "room_create_entry" else "join"
        new_state = replace(state, phase="room_pending_ack", pending_room_action=kind)
        message = CreateRoomMessage(room_id=value) if kind == "create" else JoinRoomMessage(room_id=value)
        return new_state, message
    if key == _BACKSPACE_KEY:
        return replace(state, text_entry_value=state.text_entry_value[:-1]), None
    if 32 <= key <= 126 and len(state.text_entry_value) < protocol.MAX_ROOM_ID_LENGTH:
        return replace(state, text_entry_value=state.text_entry_value + chr(key)), None
    return state, None  # arrow/function keys, -1 (no key this frame), cap already hit, etc.


def _apply_login_key_press(key: int, state: ClientState) -> Tuple[ClientState, Optional[Any]]:
    """The login screen's own key handling - two fields instead of one,
    Tab switches which is active, Enter submits as a login (the more
    common case; Register still needs its own button click). No
    Escape-cancels-to-lobby here (unlike the room text-entry phases) -
    there's nothing before the login screen to cancel back to, so
    Escape falls through to run_client's default "close the window"."""
    if key == _TAB_KEY:
        other_field = "password" if state.login_active_field == "username" else "username"
        return replace(state, login_active_field=other_field), None
    if key in _ENTER_KEYS:
        return state, _build_login_message(state, LoginMessage)
    active_value = state.login_username_value if state.login_active_field == "username" else state.login_password_value
    if key == _BACKSPACE_KEY:
        return _replace_active_login_field(state, active_value[:-1]), None
    if 32 <= key <= 126 and len(active_value) < _MAX_LOGIN_FIELD_LENGTH:
        return _replace_active_login_field(state, active_value + chr(key)), None
    return state, None


def _replace_active_login_field(state: ClientState, new_value: str) -> ClientState:
    if state.login_active_field == "username":
        return replace(state, login_username_value=new_value)
    return replace(state, login_password_value=new_value)


def _build_login_message(state: ClientState, message_type) -> Optional[Any]:
    """LoginMessage or RegisterMessage from whatever's currently typed
    into the two login fields - None (a no-op click/Enter) if either
    is still empty, the same "don't submit a blank value" guard
    apply_key_press's room text-entry Enter handler already uses."""
    username = state.login_username_value.strip()
    password = state.login_password_value
    if not username or not password:
        return None
    return message_type(username=username, password=password)


def _point_in_rect(x: int, y: int, rect) -> bool:
    rect_x, rect_y, width, height = rect
    return rect_x <= x < rect_x + width and rect_y <= y < rect_y + height

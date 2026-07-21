from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, Optional, Tuple

from kungfu_chess.client.client_state import ClientState
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.server import protocol
from kungfu_chess.server.messages import (
    CancelRoomMessage,
    CreateRoomMessage,
    JoinRoomMessage,
    JumpMessage,
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
    play_button_rect,
    room_pending_cancel_button_rect,
    text_entry_cancel_button_rect,
)
from kungfu_chess.view.renderer import game_over_button_rect

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

_ENTER_KEYS = (13, 10)
_BACKSPACE_KEY = 8
_TEXT_ENTRY_PHASES = ("room_create_entry", "room_join_entry")


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
    if state.phase != "matched" or state.view_state is None:
        return None
    if state.matched_at is not None and time.perf_counter() - state.matched_at < STARTING_DURATION_S:
        return None  # still in the starting countdown - no board is shown yet, ignore clicks
    if state.opponent_disconnected_at is not None:
        return None  # opponent is disconnected - the countdown screen is shown instead of the board

    if is_left_click:
        view_state = state.view_state
        if view_state.game_over:
            button_rect = game_over_button_rect(view_state.width, view_state.height, cell_size)
            if _point_in_rect(x, y - TOP_BANNER_HEIGHT, button_rect):
                return RestartMessage()
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
    """Pure: one raw cv2 key code (as returned by Img.show(), unmasked
    - the same convention view/image_view.py's own ESC_KEY check
    already relies on) plus the current state -> (new state, message
    to send or None). A no-op for every phase except the two text-
    entry ones, mirroring decide_message's own phase gating."""
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


def _point_in_rect(x: int, y: int, rect) -> bool:
    rect_x, rect_y, width, height = rect
    return rect_x <= x < rect_x + width and rect_y <= y < rect_y + height

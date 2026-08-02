from __future__ import annotations

import logging
import threading
from dataclasses import replace
from typing import Callable, Dict

import cv2

from kungfu_chess.assets_config import DEFAULT_PIECE_SET
from kungfu_chess.client import token_store
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
from kungfu_chess.client.network_transport import ClientBox, network_thread_main, send
from kungfu_chess.client.phases import Phase
from kungfu_chess.io.board_parser import build_board
from kungfu_chess.server.messages import LoginMessage, RegisterMessage, TokenLoginMessage
from kungfu_chess.starting_position import STARTING_POSITION
from kungfu_chess.view import image_view
from kungfu_chess.view.network_presentation import TOP_BANNER_HEIGHT, render_frame, screen_size, text_screen
from kungfu_chess.view.renderer import Renderer, side_panel_width_for
from kungfu_chess.input.board_mapper import BoardMapper

"""The networked counterpart of image_view.run() - opens the window,
owns the render loop and the mouse/keyboard handling, and wires the
other client layers together: client/network_transport.py (connection
+ background thread), client/input_controller.py (click/keystroke ->
message or local state change), client/client_state.py (what we
know), view/network_presentation.py (state -> pixels). No game logic
lives here - it moved server-side (see kungfu_chess/server/) - this
module is just the glue.

The window opens immediately, before any network connection exists -
the player picks a piece skin (skin_menu phase) and then logs in or
registers (login_entry phase) entirely locally; only once one of those
is actually submitted does _dispatch below start network_thread_main,
the same way it was always started, just later than before."""

logger = logging.getLogger(__name__)


def run_client(server_uri: str, cell_size: int, piece_set: str = DEFAULT_PIECE_SET) -> None:
    image_view._disable_windows_dpi_scaling()
    cv2.namedWindow(image_view.WINDOW_NAME)

    box = ClientBox(state=ClientState(phase=Phase.SKIN_MENU), piece_set=piece_set)

    # A throwaway local board, used only so BoardMapper can bounds-check clicks - no game logic reads it.
    bounds_board = build_board(STARTING_POSITION)
    side_panel_width = side_panel_width_for(cell_size)
    mapper = BoardMapper(bounds_board, cell_size=cell_size, x_offset=side_panel_width, y_offset=TOP_BANNER_HEIGHT)
    screen_width, screen_height = screen_size(cell_size)

    def on_mouse(event: int, x: int, y: int, flags: int, param: object) -> None:
        try:
            message = decide_message(
                box.state,
                is_left_click=event == cv2.EVENT_LBUTTONDOWN,
                is_right_click=event == cv2.EVENT_RBUTTONDOWN,
                x=x, y=y,
                mapper=mapper, cell_size=cell_size,
                screen_width=screen_width, screen_height=screen_height,
            )
        except Exception:
            # cv2 invokes this callback directly from its own C++ event
            # loop - an uncaught exception here has nowhere good to go,
            # so this is caught (and logged with the full traceback,
            # unlike every other except-block in this project) rather
            # than risking it silently wedging the window.
            logger.exception("decide_message failed for a click in phase=%s", box.state.phase)
            return
        _dispatch(box, server_uri, message)

    cv2.setMouseCallback(image_view.WINDOW_NAME, on_mouse)
    frame_renderer = Renderer()

    try:
        while True:
            try:
                canvas = render_frame(box.state, cell_size, box.piece_set, frame_renderer)
            except Exception:
                # A crash here used to mean the loop dies silently and
                # the window just freezes on whatever it last drew (no
                # error visible anywhere) - logged with the full
                # traceback so a real bug is diagnosable, and a plain
                # fallback screen shown so it's visibly stuck instead
                # of just gone quiet.
                logger.exception("render_frame failed for phase=%s", box.state.phase)
                canvas = text_screen(*screen_size(cell_size), "Rendering error - see client.log")
            key = canvas.show(image_view.WINDOW_NAME, wait_ms=image_view.TARGET_FRAME_MS)

            # apply_key_press only ever does anything while in the login
            # screen or a text-entry phase - captured before the call so
            # the quit-check below can tell "Escape cancelled text entry"
            # apart from "Escape should close the window", without both
            # firing on the same keystroke. The login screen deliberately
            # isn't included - see input_controller._apply_login_key_press.
            was_text_entry = box.state.phase in (Phase.ROOM_CREATE_ENTRY, Phase.ROOM_JOIN_ENTRY)
            try:
                new_state, message = apply_key_press(key, box.state)
            except Exception:
                logger.exception("apply_key_press failed for key=%s phase=%s", key, box.state.phase)
                new_state, message = box.state, None
            box.state = new_state
            _dispatch(box, server_uri, message)
            escape_consumed_by_text_entry = was_text_entry and key == image_view.ESC_KEY

            window_closed = cv2.getWindowProperty(image_view.WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1
            if (key == image_view.ESC_KEY and not escape_consumed_by_text_entry) or window_closed:
                break
    finally:
        cv2.destroyAllWindows()


# One handler per local sentinel, dispatched through _SENTINEL_HANDLERS
# below by the sentinel's own value (each is a unique string - see
# input_controller.py) rather than a growing if/elif chain, the same
# dispatch-table pattern used throughout the server (client_state.py's
# _HANDLERS, matchmaker.py's _lobby_handlers, game_room.py's
# _MESSAGE_HANDLERS) - just keyed by value here instead of by type.
def _create_room_button_clicked(box: ClientBox) -> None:
    box.state = ClientState(phase=Phase.ROOM_CREATE_ENTRY, rating=box.state.rating)


def _join_room_button_clicked(box: ClientBox) -> None:
    box.state = ClientState(phase=Phase.ROOM_JOIN_ENTRY, rating=box.state.rating)


def _text_entry_cancel_clicked(box: ClientBox) -> None:
    box.state = ClientState(phase=Phase.LOBBY, rating=box.state.rating)


def _fresh_login_entry_state() -> ClientState:
    """A saved session (client/token_store.py, Stage 1b) found on disk
    drives the login screen's "Continue as X" button - checked fresh
    each time the login screen is (re)entered, not carried in box.state
    beforehand, since nothing before this point has any use for it."""
    saved = token_store.load_token()
    if saved is None:
        return ClientState(phase=Phase.LOGIN_ENTRY)
    saved_username, saved_token = saved
    return ClientState(phase=Phase.LOGIN_ENTRY, saved_username=saved_username, saved_token=saved_token)


def _skin_pieces1_selected(box: ClientBox) -> None:
    box.piece_set, box.state = "pieces1", _fresh_login_entry_state()


def _skin_pieces2_selected(box: ClientBox) -> None:
    box.piece_set, box.state = "pieces2", _fresh_login_entry_state()


def _skin_pieces3_selected(box: ClientBox) -> None:
    box.piece_set, box.state = "pieces3", _fresh_login_entry_state()


def _login_field_username_clicked(box: ClientBox) -> None:
    box.state = replace(box.state, login_active_field="username")


def _login_field_password_clicked(box: ClientBox) -> None:
    box.state = replace(box.state, login_active_field="password")


_SENTINEL_HANDLERS: Dict[str, Callable[[ClientBox], None]] = {
    CREATE_ROOM_BUTTON_CLICKED: _create_room_button_clicked,
    JOIN_ROOM_BUTTON_CLICKED: _join_room_button_clicked,
    TEXT_ENTRY_CANCEL_CLICKED: _text_entry_cancel_clicked,
    SKIN_PIECES1_SELECTED: _skin_pieces1_selected,
    SKIN_PIECES2_SELECTED: _skin_pieces2_selected,
    SKIN_PIECES3_SELECTED: _skin_pieces3_selected,
    LOGIN_FIELD_USERNAME_CLICKED: _login_field_username_clicked,
    LOGIN_FIELD_PASSWORD_CLICKED: _login_field_password_clicked,
}


def _dispatch(box: ClientBox, server_uri: str, message: object) -> None:
    """Shared by on_mouse and the key-press handling above - a local
    sentinel gets a direct ClientState transition (via
    _SENTINEL_HANDLERS); a LoginMessage/RegisterMessage/TokenLoginMessage
    (only ever produced while phase == "login_entry", see
    input_controller.py - the last one Stage 1b's "Continue as X"
    button) starts the network thread instead of being sent, since no
    connection exists yet at that point; anything else is sent over
    the connection network_transport.py already owns (this is also how
    a lobby LogoutMessage reaches the server - the connection is
    already open by then). Every protocol message is a frozen (hashable)
    dataclass - see server/messages.py - so looking one up in
    _SENTINEL_HANDLERS (which never matches, since only the local string
    sentinels are keys in it) is always safe."""
    handler = _SENTINEL_HANDLERS.get(message)
    if handler is not None:
        handler(box)
        return
    if isinstance(message, (LoginMessage, RegisterMessage, TokenLoginMessage)):
        box.state = replace(box.state, phase=Phase.CONNECTING)
        threading.Thread(target=network_thread_main, args=(server_uri, message, box), daemon=True).start()
        return
    if message is not None:
        send(box, message)

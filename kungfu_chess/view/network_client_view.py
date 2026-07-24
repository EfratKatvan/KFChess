from __future__ import annotations

import logging
import threading
from dataclasses import replace

import cv2

from kungfu_chess.assets_config import DEFAULT_PIECE_SET
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
from kungfu_chess.io.board_parser import build_board
from kungfu_chess.server.messages import LoginMessage, RegisterMessage
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

    box = ClientBox(state=ClientState(phase="skin_menu"), piece_set=piece_set)

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
            was_text_entry = box.state.phase in ("room_create_entry", "room_join_entry")
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


def _dispatch(box: ClientBox, server_uri: str, message: object) -> None:
    """Shared by on_mouse and the key-press handling below - a local
    sentinel gets a direct ClientState transition; a LoginMessage/
    RegisterMessage (only ever produced while phase == "login_entry",
    see input_controller.py) starts the network thread instead of
    being sent, since no connection exists yet at that point; anything
    else is sent over the connection network_transport.py already owns."""
    if message == CREATE_ROOM_BUTTON_CLICKED:
        box.state = ClientState(phase="room_create_entry", rating=box.state.rating)
    elif message == JOIN_ROOM_BUTTON_CLICKED:
        box.state = ClientState(phase="room_join_entry", rating=box.state.rating)
    elif message == TEXT_ENTRY_CANCEL_CLICKED:
        box.state = ClientState(phase="lobby", rating=box.state.rating)
    elif message == SKIN_PIECES1_SELECTED:
        box.piece_set, box.state = "pieces1", ClientState(phase="login_entry")
    elif message == SKIN_PIECES2_SELECTED:
        box.piece_set, box.state = "pieces2", ClientState(phase="login_entry")
    elif message == SKIN_PIECES3_SELECTED:
        box.piece_set, box.state = "pieces3", ClientState(phase="login_entry")
    elif message == LOGIN_FIELD_USERNAME_CLICKED:
        box.state = replace(box.state, login_active_field="username")
    elif message == LOGIN_FIELD_PASSWORD_CLICKED:
        box.state = replace(box.state, login_active_field="password")
    elif isinstance(message, (LoginMessage, RegisterMessage)):
        box.state = replace(box.state, phase="connecting")
        threading.Thread(target=network_thread_main, args=(server_uri, message, box), daemon=True).start()
    elif message is not None:
        send(box, message)

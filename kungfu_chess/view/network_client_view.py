from __future__ import annotations

import threading

import cv2

from kungfu_chess.assets_config import DEFAULT_PIECE_SET
from kungfu_chess.client.input_controller import decide_message
from kungfu_chess.client.network_transport import ClientBox, network_thread_main, send
from kungfu_chess.io.board_parser import build_board
from kungfu_chess.starting_position import STARTING_POSITION
from kungfu_chess.view import image_view
from kungfu_chess.view.network_presentation import TOP_BANNER_HEIGHT, render_frame, screen_size
from kungfu_chess.view.renderer import Renderer, side_panel_width_for
from kungfu_chess.input.board_mapper import BoardMapper

"""The networked counterpart of image_view.run() - opens the window,
owns the render loop and the mouse callback, and wires the other
client layers together: client/network_transport.py (connection +
background thread), client/input_controller.py (click -> message),
client/client_state.py (what we know), view/network_presentation.py
(state -> pixels). No game logic lives here - it moved server-side
(see kungfu_chess/server/) - this module is just the glue."""


def run_client(server_uri: str, username: str, password: str, cell_size: int, piece_set: str = DEFAULT_PIECE_SET) -> None:
    image_view._disable_windows_dpi_scaling()
    cv2.namedWindow(image_view.WINDOW_NAME)

    box = ClientBox()
    threading.Thread(target=network_thread_main, args=(server_uri, username, password, box), daemon=True).start()

    # A throwaway local board, used only so BoardMapper can bounds-check clicks - no game logic reads it.
    bounds_board = build_board(STARTING_POSITION)
    side_panel_width = side_panel_width_for(cell_size)
    mapper = BoardMapper(bounds_board, cell_size=cell_size, x_offset=side_panel_width, y_offset=TOP_BANNER_HEIGHT)
    screen_width, screen_height = screen_size(cell_size)

    def on_mouse(event: int, x: int, y: int, flags: int, param: object) -> None:
        message = decide_message(
            box.state,
            is_left_click=event == cv2.EVENT_LBUTTONDOWN,
            is_right_click=event == cv2.EVENT_RBUTTONDOWN,
            x=x, y=y,
            mapper=mapper, cell_size=cell_size,
            screen_width=screen_width, screen_height=screen_height,
        )
        if message is not None:
            send(box, message)

    cv2.setMouseCallback(image_view.WINDOW_NAME, on_mouse)
    frame_renderer = Renderer()

    try:
        while True:
            canvas = render_frame(box.state, cell_size, piece_set, frame_renderer)
            key = canvas.show(image_view.WINDOW_NAME, wait_ms=image_view.TARGET_FRAME_MS)
            window_closed = cv2.getWindowProperty(image_view.WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1
            if key == image_view.ESC_KEY or window_closed:
                break
    finally:
        cv2.destroyAllWindows()

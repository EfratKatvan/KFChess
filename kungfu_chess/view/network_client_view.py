from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Dict, Optional

import cv2
import numpy as np
from websockets.asyncio.client import connect

from kungfu_chess.assets_config import DEFAULT_PIECE_SET
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.io.board_parser import build_board
from kungfu_chess.server import protocol
from kungfu_chess.server.serialization import (
    board_view_state_from_wire,
    legal_destinations_from_wire,
    position_from_wire,
)
from kungfu_chess.starting_position import STARTING_POSITION
from kungfu_chess.view import image_view
from kungfu_chess.view.img import Img
from kungfu_chess.view.renderer import Renderer, game_over_button_rect, side_panel_width_for

"""The networked counterpart of image_view.run() - a thin renderer and
input-forwarder instead of something that owns a GameEngine locally.
All real game logic now lives server-side (see kungfu_chess/server/) -
this module only draws whatever BoardViewState the server last sent,
and forwards clicks as messages instead of calling a local Controller."""

WAITING_TEXT = "Waiting for opponent..."
NO_OPPONENT_TEXT = "No opponent found - try again later"
CONNECTING_TEXT = "Connected - waiting for game to start..."

_TEXT_COLOR_BGRA = (255, 255, 255, 255)
_BACKGROUND_COLOR_BGRA = (30, 30, 30, 255)


def _text_screen(width: int, height: int, text: str) -> Img:
    canvas = Img()
    canvas.img = np.full((height, width, 4), _BACKGROUND_COLOR_BGRA, dtype=np.uint8)
    canvas.put_text(text, 40, height // 2, 1.0, _TEXT_COLOR_BGRA, 2)
    return canvas


def _send(box: Dict[str, Any], message: dict) -> None:
    loop = box.get("loop")
    ws = box.get("ws")
    if loop is None or ws is None:
        return
    asyncio.run_coroutine_threadsafe(ws.send(json.dumps(message)), loop)


def _handle_message(raw: str, box: Dict[str, Any]) -> None:
    message = json.loads(raw)
    message_type = message.get("type")
    if message_type == protocol.WAITING_FOR_OPPONENT:
        box["phase"] = "waiting"
    elif message_type == protocol.NO_OPPONENT_FOUND:
        box["phase"] = "no_opponent"
    elif message_type == protocol.MATCH_FOUND:
        box["phase"] = "matched"
        box["color"] = message["color"]
    elif message_type == protocol.STATE:
        box["view_state"] = board_view_state_from_wire(message["board"])
        box["selected_pos"] = position_from_wire(message["your_selected_pos"])
        box["legal_destinations"] = legal_destinations_from_wire(message["your_legal_destinations"])
        box["invalid_target"] = position_from_wire(message["your_invalid_target"])


def _network_thread_main(server_uri: str, box: Dict[str, Any]) -> None:
    async def client_main() -> None:
        async with connect(server_uri) as ws:
            box["ws"] = ws
            box["loop"] = asyncio.get_running_loop()
            async for raw in ws:
                _handle_message(raw, box)

    try:
        asyncio.run(client_main())
    except Exception:
        box["phase"] = "disconnected"


def run_client(server_uri: str, cell_size: int, piece_set: str = DEFAULT_PIECE_SET) -> None:
    image_view._disable_windows_dpi_scaling()
    cv2.namedWindow(image_view.WINDOW_NAME)

    box: Dict[str, Any] = {"phase": "connecting"}
    threading.Thread(target=_network_thread_main, args=(server_uri, box), daemon=True).start()

    # A throwaway local board, used only so BoardMapper can bounds-check clicks - no game logic reads it.
    bounds_board = build_board(STARTING_POSITION)
    side_panel_width = side_panel_width_for(cell_size)
    mapper = BoardMapper(bounds_board, cell_size=cell_size, x_offset=side_panel_width)
    board_width, board_height = len(STARTING_POSITION[0]), len(STARTING_POSITION)
    screen_width = board_width * cell_size + 2 * side_panel_width
    screen_height = board_height * cell_size

    def on_mouse(event: int, x: int, y: int, flags: int, param: object) -> None:
        if box.get("phase") != "matched":
            return
        if event == cv2.EVENT_LBUTTONDOWN:
            view_state = box.get("view_state")
            if view_state is not None and view_state.game_over:
                button_rect = game_over_button_rect(view_state.width, view_state.height, cell_size)
                if image_view._point_in_rect(x, y, button_rect):
                    _send(box, {"type": protocol.RESTART})
                return
            cell = mapper.to_cell(x, y)
            if cell is not None:
                _send(box, {"type": protocol.SELECT_OR_MOVE, "row": cell.row, "col": cell.col})
        elif event == cv2.EVENT_RBUTTONDOWN:
            cell = mapper.to_cell(x, y)
            if cell is not None:
                _send(box, {"type": protocol.JUMP, "row": cell.row, "col": cell.col})

    cv2.setMouseCallback(image_view.WINDOW_NAME, on_mouse)
    frame_renderer = Renderer()

    try:
        while True:
            phase = box.get("phase", "connecting")
            if phase == "no_opponent":
                canvas = _text_screen(screen_width, screen_height, NO_OPPONENT_TEXT)
            elif phase in ("connecting", "disconnected") or box.get("view_state") is None:
                canvas = _text_screen(screen_width, screen_height, WAITING_TEXT if phase == "waiting" else CONNECTING_TEXT)
            else:
                canvas = frame_renderer.draw(
                    box["view_state"], cell_size, piece_set,
                    selected_position=box.get("selected_pos"),
                    legal_destinations=box.get("legal_destinations"),
                    invalid_target=box.get("invalid_target"),
                )

            key = canvas.show(image_view.WINDOW_NAME, wait_ms=image_view.TARGET_FRAME_MS)
            window_closed = cv2.getWindowProperty(image_view.WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1
            if key == image_view.ESC_KEY or window_closed:
                break
    finally:
        cv2.destroyAllWindows()

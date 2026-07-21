from __future__ import annotations

import time
from typing import Any, Optional

from kungfu_chess.client.client_state import ClientState
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.server.messages import JumpMessage, RestartMessage, SeekGameMessage, SelectOrMoveMessage
from kungfu_chess.view.network_presentation import STARTING_DURATION_S, TOP_BANNER_HEIGHT, play_button_rect
from kungfu_chess.view.renderer import game_over_button_rect

"""The client's Application layer: turns a raw click into an outgoing
protocol message (or nothing). Knows the game's interaction rules -
what's clickable in which phase - but nothing about cv2, sockets, or
pixels beyond hit-testing rects it's handed. run_client's on_mouse
callback is the only caller; it owns the actual cv2 event dispatch and
the network_transport.send() call."""


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
    if state.phase in ("lobby", "no_opponent"):
        if is_left_click and _point_in_rect(x, y, play_button_rect(screen_width, screen_height)):
            return SeekGameMessage()
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


def _point_in_rect(x: int, y: int, rect) -> bool:
    rect_x, rect_y, width, height = rect
    return rect_x <= x < rect_x + width and rect_y <= y < rect_y + height

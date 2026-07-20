from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Any, Optional, Set

import cv2
import numpy as np
from websockets.asyncio.client import connect

from kungfu_chess.assets_config import DEFAULT_PIECE_SET
from kungfu_chess.engine.board_view_state import BoardViewState
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.io.board_parser import build_board
from kungfu_chess.model.position import Position
from kungfu_chess.server.messages import (
    JumpMessage,
    LoginFailedMessage,
    LoginMessage,
    LoginOkMessage,
    MatchFoundMessage,
    NoOpponentFoundMessage,
    OpponentDisconnectedMessage,
    OpponentReconnectedMessage,
    RestartMessage,
    SelectOrMoveMessage,
    StateMessage,
    WaitingForOpponentMessage,
)
from kungfu_chess.server.serialization import deserialize_message, serialize_message
from kungfu_chess.starting_position import STARTING_POSITION
from kungfu_chess.view import image_view
from kungfu_chess.view.img import Img
from kungfu_chess.view.renderer import Renderer, game_over_button_rect, side_panel_width_for

"""The networked counterpart of image_view.run() - a thin renderer and
input-forwarder instead of something that owns a GameEngine locally.
All real game logic now lives server-side (see kungfu_chess/server/) -
this module only draws whatever BoardViewState the server last sent,
and forwards clicks as messages instead of calling a local Controller."""

LOGGING_IN_TEXT = "Logging in..."
WAITING_TEXT = "Waiting for opponent..."
NO_OPPONENT_TEXT = "No opponent found - try again later"

# How long the "You are White/Black - starting in N..." countdown holds
# the board back after match_found, and how long the game-over overlay
# takes to fade in (see Renderer.draw's game_over_progress).
STARTING_DURATION_S = 3.0
GAME_OVER_FADE_DURATION_S = 0.6

_TEXT_COLOR_BGRA = (255, 255, 255, 255)
_BACKGROUND_COLOR_BGRA = (30, 30, 30, 255)


@dataclass
class ClientState:
    """Everything the render loop needs to know about the match, as of
    the last message received - replaced wholesale (never mutated field
    by field) so a read from the main thread can't see a torn mix of an
    old view_state with a newer selected_pos."""

    phase: str = "connecting"  # connecting -> waiting -> matched, or login_failed/no_opponent/disconnected
    color: Optional[str] = None
    rating: Optional[int] = None
    login_failure_reason: Optional[str] = None
    view_state: Optional[BoardViewState] = None
    selected_pos: Optional[Position] = None
    legal_destinations: Set[Position] = field(default_factory=set)
    invalid_target: Optional[Position] = None
    matched_at: Optional[float] = None
    game_over_started_at: Optional[float] = None
    opponent_disconnected_at: Optional[float] = None
    opponent_disconnect_grace_seconds: Optional[int] = None


@dataclass
class ClientBox:
    """The mutable, cross-thread handoff point: the network thread
    writes ws/loop once (on connect) and state on every message; the
    main render thread only ever reads. Safe without locks because each
    attribute write/read is a single reference assignment, atomic under
    the GIL - the same idiom image_view.py uses for current["session"]."""

    state: ClientState = field(default_factory=ClientState)
    ws: Optional[Any] = None
    loop: Optional[asyncio.AbstractEventLoop] = None


def _text_screen(width: int, height: int, text: str) -> Img:
    canvas = Img()
    canvas.img = np.full((height, width, 4), _BACKGROUND_COLOR_BGRA, dtype=np.uint8)
    canvas.put_text(text, 40, height // 2, 1.0, _TEXT_COLOR_BGRA, 2)
    return canvas


def _starting_text(color: Optional[str], remaining_s: float) -> str:
    you_are = f"You are {color.capitalize()} - " if color else ""
    if remaining_s <= 0:
        return f"{you_are}GO!"
    return f"{you_are}starting in {int(remaining_s) + 1}..."


def _disconnect_text(remaining_s: float) -> str:
    if remaining_s <= 0:
        return "Opponent disconnected - resigning..."
    return f"Opponent disconnected - auto-resign in {int(remaining_s) + 1}..."


def _send(box: ClientBox, message: Any) -> None:
    if box.loop is None or box.ws is None:
        return
    asyncio.run_coroutine_threadsafe(box.ws.send(serialize_message(message)), box.loop)


def _game_over_started_at(previous: Optional[float], board_game_over: bool) -> Optional[float]:
    """Tracks the moment game_over first turned True (for the fade-in
    animation) - set once on the transition, cleared once a fresh game
    (restart) reports game_over False again."""
    if not board_game_over:
        return None
    return previous if previous is not None else time.perf_counter()


def _handle_message(raw: str, box: ClientBox) -> None:
    message = deserialize_message(raw)
    if isinstance(message, LoginOkMessage):
        box.state = ClientState(phase="connecting", rating=message.rating)  # server moves straight on to matchmaking next
    elif isinstance(message, LoginFailedMessage):
        box.state = ClientState(phase="login_failed", login_failure_reason=message.reason)
    elif isinstance(message, WaitingForOpponentMessage):
        box.state = ClientState(phase="waiting")
    elif isinstance(message, NoOpponentFoundMessage):
        box.state = ClientState(phase="no_opponent")
    elif isinstance(message, MatchFoundMessage):
        box.state = ClientState(phase="matched", color=message.color, matched_at=time.perf_counter())
    elif isinstance(message, OpponentDisconnectedMessage):
        box.state = replace(
            box.state,
            opponent_disconnected_at=time.perf_counter(),
            opponent_disconnect_grace_seconds=message.grace_seconds,
        )
    elif isinstance(message, OpponentReconnectedMessage):
        box.state = replace(box.state, opponent_disconnected_at=None, opponent_disconnect_grace_seconds=None)
    elif isinstance(message, StateMessage):
        box.state = ClientState(
            phase="matched",
            color=box.state.color,
            view_state=message.board,
            selected_pos=message.your_selected_pos,
            legal_destinations=message.your_legal_destinations,
            invalid_target=message.your_invalid_target,
            matched_at=box.state.matched_at,
            game_over_started_at=_game_over_started_at(box.state.game_over_started_at, message.board.game_over),
            opponent_disconnected_at=box.state.opponent_disconnected_at,
            opponent_disconnect_grace_seconds=box.state.opponent_disconnect_grace_seconds,
        )


def _network_thread_main(server_uri: str, username: str, password: str, box: ClientBox) -> None:
    async def client_main() -> None:
        async with connect(server_uri) as ws:
            box.ws = ws
            box.loop = asyncio.get_running_loop()
            await ws.send(serialize_message(LoginMessage(username=username, password=password)))
            async for raw in ws:
                _handle_message(raw, box)

    try:
        asyncio.run(client_main())
    except Exception:
        box.state = ClientState(phase="disconnected")


def run_client(server_uri: str, username: str, password: str, cell_size: int, piece_set: str = DEFAULT_PIECE_SET) -> None:
    image_view._disable_windows_dpi_scaling()
    cv2.namedWindow(image_view.WINDOW_NAME)

    box = ClientBox()
    threading.Thread(target=_network_thread_main, args=(server_uri, username, password, box), daemon=True).start()

    # A throwaway local board, used only so BoardMapper can bounds-check clicks - no game logic reads it.
    bounds_board = build_board(STARTING_POSITION)
    side_panel_width = side_panel_width_for(cell_size)
    mapper = BoardMapper(bounds_board, cell_size=cell_size, x_offset=side_panel_width)
    board_width, board_height = len(STARTING_POSITION[0]), len(STARTING_POSITION)
    screen_width = board_width * cell_size + 2 * side_panel_width
    screen_height = board_height * cell_size

    def on_mouse(event: int, x: int, y: int, flags: int, param: object) -> None:
        state = box.state
        if state.phase != "matched" or state.view_state is None:
            return
        if state.matched_at is not None and time.perf_counter() - state.matched_at < STARTING_DURATION_S:
            return  # still in the starting countdown - no board is shown yet, ignore clicks
        if state.opponent_disconnected_at is not None:
            return  # opponent is disconnected - the countdown screen is shown instead of the board
        if event == cv2.EVENT_LBUTTONDOWN:
            view_state = state.view_state
            if view_state.game_over:
                button_rect = game_over_button_rect(view_state.width, view_state.height, cell_size)
                if image_view._point_in_rect(x, y, button_rect):
                    _send(box, RestartMessage())
                return
            cell = mapper.to_cell(x, y)
            if cell is not None:
                _send(box, SelectOrMoveMessage(row=cell.row, col=cell.col))
        elif event == cv2.EVENT_RBUTTONDOWN:
            cell = mapper.to_cell(x, y)
            if cell is not None:
                _send(box, JumpMessage(row=cell.row, col=cell.col))

    cv2.setMouseCallback(image_view.WINDOW_NAME, on_mouse)
    frame_renderer = Renderer()

    try:
        while True:
            state = box.state
            starting_remaining_s = (
                STARTING_DURATION_S - (time.perf_counter() - state.matched_at)
                if state.matched_at is not None else None
            )
            disconnect_remaining_s = (
                state.opponent_disconnect_grace_seconds - (time.perf_counter() - state.opponent_disconnected_at)
                if state.opponent_disconnected_at is not None else None
            )

            if state.phase == "login_failed":
                canvas = _text_screen(screen_width, screen_height, f"Login failed: {state.login_failure_reason}")
            elif state.phase == "no_opponent":
                canvas = _text_screen(screen_width, screen_height, NO_OPPONENT_TEXT)
            elif starting_remaining_s is not None and starting_remaining_s > 0:
                canvas = _text_screen(screen_width, screen_height, _starting_text(state.color, starting_remaining_s))
            elif disconnect_remaining_s is not None and disconnect_remaining_s > 0:
                canvas = _text_screen(screen_width, screen_height, _disconnect_text(disconnect_remaining_s))
            elif state.phase in ("connecting", "disconnected") or state.view_state is None:
                canvas = _text_screen(screen_width, screen_height, WAITING_TEXT if state.phase == "waiting" else LOGGING_IN_TEXT)
            else:
                game_over_progress = 1.0
                if state.game_over_started_at is not None:
                    elapsed_s = time.perf_counter() - state.game_over_started_at
                    game_over_progress = min(1.0, elapsed_s / GAME_OVER_FADE_DURATION_S)
                canvas = frame_renderer.draw(
                    state.view_state, cell_size, piece_set,
                    selected_position=state.selected_pos,
                    legal_destinations=state.legal_destinations,
                    invalid_target=state.invalid_target,
                    game_over_progress=game_over_progress,
                )

            key = canvas.show(image_view.WINDOW_NAME, wait_ms=image_view.TARGET_FRAME_MS)
            window_closed = cv2.getWindowProperty(image_view.WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1
            if key == image_view.ESC_KEY or window_closed:
                break
    finally:
        cv2.destroyAllWindows()

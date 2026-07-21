from __future__ import annotations

import time
from typing import Optional, Tuple

import numpy as np

from kungfu_chess.client.client_state import ClientState, PlayerInfo
from kungfu_chess.model.piece import WHITE
from kungfu_chess.starting_position import STARTING_POSITION
from kungfu_chess.view.img import Img
from kungfu_chess.view.renderer import Renderer, side_panel_width_for

"""The client's Presentation layer: pure functions from ClientState to
pixels. Nothing here touches the network or decides what a click
should do - see client/network_transport.py and
client/input_controller.py for those. render_frame is the one entry
point run_client's loop actually calls; everything else here is a
drawing helper it (or a test) composes."""

LOGGING_IN_TEXT = "Logging in..."
WAITING_TEXT = "Waiting for opponent..."
NO_OPPONENT_TEXT = "No opponent found - try again later"
DISCONNECTED_TEXT = "Disconnected from server - please restart"

PLAY_BUTTON_TEXT = "PLAY"
PLAY_BUTTON_WIDTH = 200
PLAY_BUTTON_HEIGHT = 56
PLAY_BUTTON_COLOR_BGRA = (70, 70, 70, 255)
PLAY_BUTTON_BORDER_COLOR_BGRA = (255, 255, 255, 255)
PLAY_BUTTON_BORDER_THICKNESS = 2
PLAY_BUTTON_FONT_SIZE = 0.9
PLAY_BUTTON_TEXT_THICKNESS = 2

CREATE_ROOM_BUTTON_TEXT = "CREATE ROOM"
JOIN_ROOM_BUTTON_TEXT = "JOIN ROOM"
CANCEL_BUTTON_TEXT = "CANCEL"
LOBBY_BUTTON_GAP_Y = 16  # vertical gap between each stacked lobby button

TEXT_ENTRY_BOX_WIDTH = 360
TEXT_ENTRY_BOX_HEIGHT = 48
TEXT_ENTRY_BOX_COLOR_BGRA = (50, 50, 50, 255)
TEXT_ENTRY_BOX_BORDER_COLOR_BGRA = (255, 255, 255, 255)
TEXT_ENTRY_CURSOR = "|"
TEXT_ENTRY_HINT_TEXT = "Enter to confirm  -  Esc to cancel"
CREATE_ROOM_ENTRY_TITLE = "Choose a room name:"
JOIN_ROOM_ENTRY_TITLE = "Enter a room name to join:"

# How long the "You are White/Black - starting in N..." countdown holds
# the board back after match_found, and how long the game-over overlay
# takes to fade in (see Renderer.draw's game_over_progress).
STARTING_DURATION_S = 3.0
GAME_OVER_FADE_DURATION_S = 0.6

_TEXT_COLOR_BGRA = (255, 255, 255, 255)
_BACKGROUND_COLOR_BGRA = (30, 30, 30, 255)

# Top banner shown above the board once matched - "You: name (rating)" on
# the left, the opponent's identity on the right. Drawn separately from
# Renderer.draw() (which only knows the board) so it's shown once, not
# duplicated per side panel.
TOP_BANNER_HEIGHT = 44
TOP_BANNER_COLOR_BGRA = (20, 20, 20, 255)
TOP_BANNER_ACCENT_COLOR_BGRA = (0, 255, 255, 255)
TOP_BANNER_FONT_SIZE = 0.65
TOP_BANNER_TEXT_THICKNESS = 2
TOP_BANNER_PADDING_X = 16

_BOARD_WIDTH_CELLS = len(STARTING_POSITION[0])
_BOARD_HEIGHT_CELLS = len(STARTING_POSITION)


def screen_size(cell_size: int) -> Tuple[int, int]:
    """The fixed (width, height) of the whole client window at this
    cell_size - the board plus both side panels, not including the top
    banner (that's added on top only once matched, see render_frame)."""
    side_panel_width = side_panel_width_for(cell_size)
    return (
        _BOARD_WIDTH_CELLS * cell_size + 2 * side_panel_width,
        _BOARD_HEIGHT_CELLS * cell_size,
    )


def text_screen(width: int, height: int, text: str) -> Img:
    canvas = Img()
    canvas.img = np.full((height, width, 4), _BACKGROUND_COLOR_BGRA, dtype=np.uint8)
    canvas.put_text(text, 40, height // 2, 1.0, _TEXT_COLOR_BGRA, 2)
    return canvas


def play_button_rect(width: int, height: int) -> Tuple[int, int, int, int]:
    """Shared by drawing (draw_play_button) and click hit-testing (see
    client/input_controller.py) - same reasoning as
    renderer.py's game_over_button_rect."""
    return (
        width // 2 - PLAY_BUTTON_WIDTH // 2,
        height // 2 + 20,
        PLAY_BUTTON_WIDTH,
        PLAY_BUTTON_HEIGHT,
    )


def _draw_button(canvas: Img, x: int, y: int, w: int, h: int, text: str) -> None:
    """Shared body for every button drawn in this module (Play, Create
    Room, Join Room, and every Cancel button) - each caller owns its
    own *_rect function for positioning/hit-testing (see
    client/input_controller.py), this just draws the box+label."""
    canvas.draw_rect(x, y, w, h, PLAY_BUTTON_COLOR_BGRA, -1)
    canvas.draw_rect(x, y, w, h, PLAY_BUTTON_BORDER_COLOR_BGRA, PLAY_BUTTON_BORDER_THICKNESS)
    text_w, text_h = canvas.text_size(text, PLAY_BUTTON_FONT_SIZE, PLAY_BUTTON_TEXT_THICKNESS)
    canvas.put_text(
        text, x + w // 2 - text_w // 2, y + h // 2 + text_h // 2,
        PLAY_BUTTON_FONT_SIZE, _TEXT_COLOR_BGRA, PLAY_BUTTON_TEXT_THICKNESS,
    )


def create_room_button_rect(width: int, height: int) -> Tuple[int, int, int, int]:
    """Sits directly below the Play button - shared by drawing
    (lobby_screen) and click hit-testing (see
    client/input_controller.py), same reasoning as play_button_rect."""
    play_x, play_y, play_w, play_h = play_button_rect(width, height)
    return (
        width // 2 - PLAY_BUTTON_WIDTH // 2,
        play_y + play_h + LOBBY_BUTTON_GAP_Y,
        PLAY_BUTTON_WIDTH,
        PLAY_BUTTON_HEIGHT,
    )


def join_room_button_rect(width: int, height: int) -> Tuple[int, int, int, int]:
    """Sits directly below the Create Room button."""
    create_x, create_y, create_w, create_h = create_room_button_rect(width, height)
    return (
        width // 2 - PLAY_BUTTON_WIDTH // 2,
        create_y + create_h + LOBBY_BUTTON_GAP_Y,
        PLAY_BUTTON_WIDTH,
        PLAY_BUTTON_HEIGHT,
    )


def lobby_screen(width: int, height: int, rating: Optional[int], message: Optional[str] = None) -> Img:
    """The pre-matchmaking screen: shows the player's rating and three
    separate buttons - Play (ELO-ranged matchmaking, see
    Matchmaker._start_seeking), Create Room and Join Room (each opens
    its own in-canvas text-entry screen, see
    client/input_controller.py's apply_key_press). Also reused for the
    "no opponent found"/"room action failed" screens (with message
    set) so the player can retry without restarting the app."""
    canvas = Img()
    canvas.img = np.full((height, width, 4), _BACKGROUND_COLOR_BGRA, dtype=np.uint8)
    title = f"Rating: {rating}" if rating is not None else "Ready to play"
    canvas.put_text(title, 40, height // 2 - 60, 1.0, _TEXT_COLOR_BGRA, 2)
    if message is not None:
        canvas.put_text(message, 40, height // 2 - 20, 0.6, _TEXT_COLOR_BGRA, 1)
    _draw_button(canvas, *play_button_rect(width, height), PLAY_BUTTON_TEXT)
    _draw_button(canvas, *create_room_button_rect(width, height), CREATE_ROOM_BUTTON_TEXT)
    _draw_button(canvas, *join_room_button_rect(width, height), JOIN_ROOM_BUTTON_TEXT)
    return canvas


def room_pending_cancel_button_rect(width: int, height: int) -> Tuple[int, int, int, int]:
    return (
        width // 2 - PLAY_BUTTON_WIDTH // 2,
        height // 2 + 60,
        PLAY_BUTTON_WIDTH,
        PLAY_BUTTON_HEIGHT,
    )


def room_pending_screen(width: int, height: int, room_id: Optional[str], rating: Optional[int]) -> Img:
    """Shown after Create/Join while waiting for the room's opponent
    seat to fill - the "writes it on top of the screen" moment from the
    spec, kept on screen (not just flashed once) until the game starts.
    Includes a Cancel button - without it the creator would have no way
    at all to back out of a pending room before someone joins."""
    canvas = Img()
    canvas.img = np.full((height, width, 4), _BACKGROUND_COLOR_BGRA, dtype=np.uint8)
    canvas.put_text(f"Room: {room_id}", 40, height // 2 - 40, 1.0, _TEXT_COLOR_BGRA, 2)
    canvas.put_text("Waiting for opponent...", 40, height // 2, 0.7, _TEXT_COLOR_BGRA, 1)
    if rating is not None:
        canvas.put_text(f"Rating: {rating}", 40, height // 2 + 40, 0.6, _TEXT_COLOR_BGRA, 1)
    _draw_button(canvas, *room_pending_cancel_button_rect(width, height), CANCEL_BUTTON_TEXT)
    return canvas


def text_entry_box_rect(width: int, height: int) -> Tuple[int, int, int, int]:
    return (
        width // 2 - TEXT_ENTRY_BOX_WIDTH // 2,
        height // 2 - 20,
        TEXT_ENTRY_BOX_WIDTH,
        TEXT_ENTRY_BOX_HEIGHT,
    )


def text_entry_cancel_button_rect(width: int, height: int) -> Tuple[int, int, int, int]:
    _, box_y, _, box_h = text_entry_box_rect(width, height)
    return (
        width // 2 - PLAY_BUTTON_WIDTH // 2,
        box_y + box_h + 40,
        PLAY_BUTTON_WIDTH,
        PLAY_BUTTON_HEIGHT,
    )


def text_entry_screen(width: int, height: int, title: str, value: str) -> Img:
    """The Create Room / Join Room text-entry screen - a title, a
    drawn text box showing what's been typed so far plus a static
    cursor (no timer/animation plumbing exists in this codebase to
    blink one), a hint line, and a Cancel button (mirrors the Escape
    key handled by client/input_controller.py's apply_key_press, so
    cancelling is discoverable without needing to know the shortcut)."""
    canvas = Img()
    canvas.img = np.full((height, width, 4), _BACKGROUND_COLOR_BGRA, dtype=np.uint8)
    title_w, _ = canvas.text_size(title, 0.8, 2)
    canvas.put_text(title, width // 2 - title_w // 2, height // 2 - 60, 0.8, _TEXT_COLOR_BGRA, 2)

    box_x, box_y, box_w, box_h = text_entry_box_rect(width, height)
    canvas.draw_rect(box_x, box_y, box_w, box_h, TEXT_ENTRY_BOX_COLOR_BGRA, -1)
    canvas.draw_rect(box_x, box_y, box_w, box_h, TEXT_ENTRY_BOX_BORDER_COLOR_BGRA, 2)
    canvas.put_text(value + TEXT_ENTRY_CURSOR, box_x + 12, box_y + box_h // 2 + 8, 0.7, _TEXT_COLOR_BGRA, 2)

    hint_w, _ = canvas.text_size(TEXT_ENTRY_HINT_TEXT, 0.5, 1)
    canvas.put_text(TEXT_ENTRY_HINT_TEXT, width // 2 - hint_w // 2, box_y + box_h + 24, 0.5, _TEXT_COLOR_BGRA, 1)
    _draw_button(canvas, *text_entry_cancel_button_rect(width, height), CANCEL_BUTTON_TEXT)
    return canvas


def _draw_top_banner(
    canvas: Img, width: int,
    white_player: PlayerInfo, black_player: PlayerInfo,
    viewer_color: Optional[str], room_id: Optional[str] = None,
) -> None:
    """Draws the identity bar at canvas(0, 0) - "You: name (rating)" on
    the left for a player (viewer_color set), or "White: ..."/"Black:
    ..." for a spectator (viewer_color is None, since they play no
    side) - plus the room id centered, if this game came from one.
    Caller must have already sized canvas with at least
    TOP_BANNER_HEIGHT of room at the top."""
    canvas.draw_rect(0, 0, width, TOP_BANNER_HEIGHT, TOP_BANNER_COLOR_BGRA, -1)
    text_y = TOP_BANNER_HEIGHT // 2 + 6

    if viewer_color is None:
        left_text = f"White: {white_player.username} ({white_player.rating})"
        right_text = f"Black: {black_player.username} ({black_player.rating})"
        left_color = _TEXT_COLOR_BGRA
    else:
        your_player = white_player if viewer_color == WHITE else black_player
        opponent_player = black_player if viewer_color == WHITE else white_player
        left_text = f"You: {your_player.username} ({your_player.rating})"
        right_text = f"{opponent_player.username} ({opponent_player.rating})"
        left_color = TOP_BANNER_ACCENT_COLOR_BGRA

    canvas.put_text(left_text, TOP_BANNER_PADDING_X, text_y, TOP_BANNER_FONT_SIZE, left_color, TOP_BANNER_TEXT_THICKNESS)
    right_text_w, _ = canvas.text_size(right_text, TOP_BANNER_FONT_SIZE, TOP_BANNER_TEXT_THICKNESS)
    canvas.put_text(
        right_text, width - right_text_w - TOP_BANNER_PADDING_X, text_y,
        TOP_BANNER_FONT_SIZE, _TEXT_COLOR_BGRA, TOP_BANNER_TEXT_THICKNESS,
    )

    if room_id is not None:
        room_text = f"Room: {room_id}"
        room_text_w, _ = canvas.text_size(room_text, TOP_BANNER_FONT_SIZE, TOP_BANNER_TEXT_THICKNESS)
        canvas.put_text(
            room_text, width // 2 - room_text_w // 2, text_y,
            TOP_BANNER_FONT_SIZE, _TEXT_COLOR_BGRA, TOP_BANNER_TEXT_THICKNESS,
        )


def starting_text(color: Optional[str], remaining_s: float) -> str:
    you_are = f"You are {color.capitalize()} - " if color else ""
    if remaining_s <= 0:
        return f"{you_are}GO!"
    return f"{you_are}starting in {int(remaining_s) + 1}..."


def disconnect_text(remaining_s: float) -> str:
    if remaining_s <= 0:
        return "Opponent disconnected - resigning..."
    return f"Opponent disconnected - auto-resign in {int(remaining_s) + 1}..."


def render_frame(state: ClientState, cell_size: int, piece_set: str, renderer: Renderer) -> Img:
    """The single entry point run_client's loop calls every frame -
    decides which screen the current phase calls for and builds it.
    Pure given (state, cell_size, piece_set, renderer) - no I/O, so
    it's independently testable without a real window/network."""
    width, height = screen_size(cell_size)

    starting_remaining_s = (
        STARTING_DURATION_S - (time.perf_counter() - state.matched_at)
        if state.matched_at is not None else None
    )
    disconnect_remaining_s = (
        state.opponent_disconnect_grace_seconds - (time.perf_counter() - state.opponent_disconnected_at)
        if state.opponent_disconnected_at is not None else None
    )

    if state.phase == "login_failed":
        return text_screen(width, height, f"Login failed: {state.login_failure_reason}")
    if state.phase == "lobby":
        return lobby_screen(width, height, state.rating)
    if state.phase == "no_opponent":
        return lobby_screen(width, height, state.rating, message=NO_OPPONENT_TEXT)
    if state.phase == "room_action_failed":
        verb = "create" if state.room_action_failure_kind == "create" else "join"
        return lobby_screen(width, height, state.rating, message=f"Could not {verb} room: {state.room_action_failure_reason}")
    if state.phase == "room_create_entry":
        return text_entry_screen(width, height, CREATE_ROOM_ENTRY_TITLE, state.text_entry_value)
    if state.phase == "room_join_entry":
        return text_entry_screen(width, height, JOIN_ROOM_ENTRY_TITLE, state.text_entry_value)
    if state.phase == "room_pending_ack":
        text = "Creating room..." if state.pending_room_action == "create" else "Joining room..."
        return text_screen(width, height, text)
    if state.phase == "room_waiting":
        return room_pending_screen(width, height, state.room_id, state.rating)
    if state.phase == "disconnected":
        return text_screen(width, height, DISCONNECTED_TEXT)
    if starting_remaining_s is not None and starting_remaining_s > 0:
        return text_screen(width, height, starting_text(state.color, starting_remaining_s))
    if disconnect_remaining_s is not None and disconnect_remaining_s > 0:
        return text_screen(width, height, disconnect_text(disconnect_remaining_s))
    if state.phase not in ("matched", "spectating") or state.view_state is None:
        return text_screen(width, height, WAITING_TEXT if state.phase == "waiting" else LOGGING_IN_TEXT)

    game_over_progress = 1.0
    if state.game_over_started_at is not None:
        elapsed_s = time.perf_counter() - state.game_over_started_at
        game_over_progress = min(1.0, elapsed_s / GAME_OVER_FADE_DURATION_S)
    board_canvas = renderer.draw(
        state.view_state, cell_size, piece_set,
        selected_position=state.selected_pos,
        legal_destinations=state.legal_destinations,
        invalid_target=state.invalid_target,
        game_over_progress=game_over_progress,
    )

    board_height_px, board_width_px = board_canvas.img.shape[:2]
    canvas = Img()
    canvas.img = np.full((board_height_px + TOP_BANNER_HEIGHT, board_width_px, 4), _BACKGROUND_COLOR_BGRA, dtype=np.uint8)
    board_canvas.draw_on(canvas, 0, TOP_BANNER_HEIGHT)
    if state.white_player is not None and state.black_player is not None:
        _draw_top_banner(canvas, board_width_px, state.white_player, state.black_player, state.color, state.room_id)
    return canvas

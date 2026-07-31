from __future__ import annotations

import time
from typing import Callable, Dict, Optional, Tuple

import numpy as np

from kungfu_chess.client.client_state import ClientState, PlayerInfo
from kungfu_chess.client.motion_tracker import apply_pending_motions
from kungfu_chess.client.phases import Phase, RoomAction
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

SKIN_MENU_TITLE = "Choose your piece set"
PIECES1_BUTTON_TEXT = "Pieces 1"
PIECES2_BUTTON_TEXT = "Pieces 2"
PIECES3_BUTTON_TEXT = "Pieces 3"

LOGIN_TITLE_TEXT = "Login or Register"
LOGIN_BUTTON_TEXT = "LOGIN"
REGISTER_BUTTON_TEXT = "REGISTER"
LOGIN_USERNAME_LABEL = "Username"
LOGIN_PASSWORD_LABEL = "Password"
LOGIN_FIELD_WIDTH = 320
LOGIN_FIELD_HEIGHT = 44
LOGIN_FIELD_GAP_Y = 24
LOGIN_FIELD_BG_COLOR_BGRA = (50, 50, 50, 255)
LOGIN_FIELD_BORDER_COLOR_BGRA = (255, 255, 255, 255)
LOGIN_FIELD_ACTIVE_BORDER_COLOR_BGRA = (0, 215, 255, 255)  # same gold as renderer.py's own selection highlight
LOGIN_FIELD_BORDER_THICKNESS = 2
LOGIN_MASK_CHAR = "*"  # password field never shows the real characters, only this
LOGIN_ERROR_COLOR_BGRA = (60, 60, 255, 255)
LOGIN_BUTTON_WIDTH = 150
LOGIN_BUTTON_GAP_X = 20

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
BACK_BUTTON_TEXT = "BACK"
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

# Resign button - lives in a reserved strip at the banner's left edge
# (a fixed rect, not measured from any text) so its position never
# depends on username/rating length, and "You: ..." always starts
# right after it - see _draw_top_banner's left_text_x.
RESIGN_BUTTON_TEXT = "Resign"
RESIGN_BUTTON_WIDTH = 80
RESIGN_BUTTON_HEIGHT = 28
RESIGN_BUTTON_Y = (TOP_BANNER_HEIGHT - RESIGN_BUTTON_HEIGHT) // 2
RESIGN_BUTTON_COLOR_BGRA = (40, 40, 150, 255)  # a muted red, distinct from every other (neutral gray) button - this one forfeits
RESIGN_BUTTON_BORDER_COLOR_BGRA = (255, 255, 255, 255)
RESIGN_BUTTON_BORDER_THICKNESS = 1
RESIGN_BUTTON_FONT_SIZE = 0.5
RESIGN_BUTTON_TEXT_THICKNESS = 1
_RESIGN_RESERVED_WIDTH = TOP_BANNER_PADDING_X + RESIGN_BUTTON_WIDTH + 12  # reserved even when not shown, so "You: ..." never jumps position

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


def skin_pieces1_button_rect(width: int, height: int) -> Tuple[int, int, int, int]:
    return (
        width // 2 - PLAY_BUTTON_WIDTH // 2,
        height // 2 - 40,
        PLAY_BUTTON_WIDTH,
        PLAY_BUTTON_HEIGHT,
    )


def skin_pieces2_button_rect(width: int, height: int) -> Tuple[int, int, int, int]:
    """Sits directly below the Pieces 1 button - same stacking as
    lobby_screen's Play/Create Room/Join Room."""
    x, y, w, h = skin_pieces1_button_rect(width, height)
    return (x, y + h + LOBBY_BUTTON_GAP_Y, w, h)


def skin_pieces3_button_rect(width: int, height: int) -> Tuple[int, int, int, int]:
    """Sits directly below the Pieces 2 button."""
    x, y, w, h = skin_pieces2_button_rect(width, height)
    return (x, y + h + LOBBY_BUTTON_GAP_Y, w, h)


def skin_menu_screen(width: int, height: int) -> Img:
    """The very first screen shown, before any network connection - a
    one-time choice of which piece sprite set (kungfu_chess/assets/
    pieces1|2|3) to render with for the rest of this run. Purely
    local/client-side; the server never learns or cares which one was
    picked (see client/input_controller.py's SKIN_*_SELECTED sentinels
    and view/network_client_view.py, which applies the choice to its
    own local piece_set variable, not to ClientState)."""
    canvas = Img()
    canvas.img = np.full((height, width, 4), _BACKGROUND_COLOR_BGRA, dtype=np.uint8)
    title_w, _ = canvas.text_size(SKIN_MENU_TITLE, 1.0, 2)
    canvas.put_text(SKIN_MENU_TITLE, width // 2 - title_w // 2, height // 2 - 100, 1.0, _TEXT_COLOR_BGRA, 2)
    _draw_button(canvas, *skin_pieces1_button_rect(width, height), PIECES1_BUTTON_TEXT)
    _draw_button(canvas, *skin_pieces2_button_rect(width, height), PIECES2_BUTTON_TEXT)
    _draw_button(canvas, *skin_pieces3_button_rect(width, height), PIECES3_BUTTON_TEXT)
    return canvas


def login_username_field_rect(width: int, height: int) -> Tuple[int, int, int, int]:
    return (
        width // 2 - LOGIN_FIELD_WIDTH // 2,
        height // 2 - 100,
        LOGIN_FIELD_WIDTH,
        LOGIN_FIELD_HEIGHT,
    )


def login_password_field_rect(width: int, height: int) -> Tuple[int, int, int, int]:
    """Sits directly below the username field."""
    x, y, w, h = login_username_field_rect(width, height)
    return (x, y + h + LOGIN_FIELD_GAP_Y, w, h)


def login_button_rect(width: int, height: int) -> Tuple[int, int, int, int]:
    """Sits below the password field, to the left of Register - the two
    share one centered row rather than stacking, since they're
    alternatives (pick one), not a sequence."""
    _, password_y, _, password_h = login_password_field_rect(width, height)
    total_width = LOGIN_BUTTON_WIDTH * 2 + LOGIN_BUTTON_GAP_X
    return (
        width // 2 - total_width // 2,
        password_y + password_h + 30,
        LOGIN_BUTTON_WIDTH,
        PLAY_BUTTON_HEIGHT,
    )


def register_button_rect(width: int, height: int) -> Tuple[int, int, int, int]:
    x, y, w, h = login_button_rect(width, height)
    return (x + w + LOGIN_BUTTON_GAP_X, y, w, h)


def _draw_login_field(canvas: Img, rect: Tuple[int, int, int, int], label: str, value: str, is_active: bool, mask: bool) -> None:
    x, y, w, h = rect
    canvas.put_text(label, x, y - 10, 0.5, _TEXT_COLOR_BGRA, 1)
    canvas.draw_rect(x, y, w, h, LOGIN_FIELD_BG_COLOR_BGRA, -1)
    border_color = LOGIN_FIELD_ACTIVE_BORDER_COLOR_BGRA if is_active else LOGIN_FIELD_BORDER_COLOR_BGRA
    canvas.draw_rect(x, y, w, h, border_color, LOGIN_FIELD_BORDER_THICKNESS)
    displayed = (LOGIN_MASK_CHAR * len(value)) if mask else value
    if is_active:
        displayed += TEXT_ENTRY_CURSOR
    canvas.put_text(displayed, x + 12, y + h // 2 + 8, 0.7, _TEXT_COLOR_BGRA, 2)


def login_entry_screen(width: int, height: int, state: ClientState) -> Img:
    """Shown right after the skin menu (or again after a rejected
    login/register, with the username kept and the password cleared -
    see client_state._on_login_failed) - collects a username and a
    masked password, then either LOGIN or REGISTER builds and sends
    the matching message (see client/input_controller.py). No network
    connection exists yet until one of those is actually submitted."""
    canvas = Img()
    canvas.img = np.full((height, width, 4), _BACKGROUND_COLOR_BGRA, dtype=np.uint8)
    title_w, _ = canvas.text_size(LOGIN_TITLE_TEXT, 1.0, 2)
    canvas.put_text(LOGIN_TITLE_TEXT, width // 2 - title_w // 2, height // 2 - 160, 1.0, _TEXT_COLOR_BGRA, 2)

    _draw_login_field(
        canvas, login_username_field_rect(width, height), LOGIN_USERNAME_LABEL,
        state.login_username_value, is_active=state.login_active_field == "username", mask=False,
    )
    _draw_login_field(
        canvas, login_password_field_rect(width, height), LOGIN_PASSWORD_LABEL,
        state.login_password_value, is_active=state.login_active_field == "password", mask=True,
    )

    _draw_button(canvas, *login_button_rect(width, height), LOGIN_BUTTON_TEXT)
    _draw_button(canvas, *register_button_rect(width, height), REGISTER_BUTTON_TEXT)

    if state.login_failure_reason is not None:
        error_text = f"Login failed: {state.login_failure_reason}"
        error_w, _ = canvas.text_size(error_text, 0.55, 1)
        _, button_y, _, button_h = login_button_rect(width, height)
        canvas.put_text(error_text, width // 2 - error_w // 2, button_y + button_h + 30, 0.55, LOGIN_ERROR_COLOR_BGRA, 1)

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


def waiting_screen(width: int, height: int, rating: Optional[int]) -> Img:
    """Shown after clicking Play, while Matchmaker._start_seeking's
    ELO-ranged queue looks for an opponent - the "Play" counterpart to
    room_pending_screen, with a Back button (see CancelSeekMessage) so
    the player isn't stuck watching this until either a match or the
    matchmaking timeout. Reuses room_pending_cancel_button_rect's
    position - both screens are just a message plus one centered
    secondary-action button below it."""
    canvas = Img()
    canvas.img = np.full((height, width, 4), _BACKGROUND_COLOR_BGRA, dtype=np.uint8)
    canvas.put_text(WAITING_TEXT, 40, height // 2 - 20, 0.7, _TEXT_COLOR_BGRA, 1)
    if rating is not None:
        canvas.put_text(f"Rating: {rating}", 40, height // 2 + 20, 0.6, _TEXT_COLOR_BGRA, 1)
    _draw_button(canvas, *room_pending_cancel_button_rect(width, height), BACK_BUTTON_TEXT)
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


def resign_button_rect(width: int, height: int) -> Tuple[int, int, int, int]:
    """A fixed rect in the top banner's left strip - width/height are
    unused (kept only so this matches every other *_button_rect
    function's (screen_width, screen_height) signature that
    client/input_controller.py's decide_message calls it with)."""
    return (TOP_BANNER_PADDING_X, RESIGN_BUTTON_Y, RESIGN_BUTTON_WIDTH, RESIGN_BUTTON_HEIGHT)


def _draw_top_banner(
    canvas: Img, width: int,
    white_player: PlayerInfo, black_player: PlayerInfo,
    viewer_color: Optional[str], room_id: Optional[str] = None,
    show_resign_button: bool = False,
) -> None:
    """Draws the identity bar at canvas(0, 0) - "You: name (rating)"
    for a player (viewer_color set), or "White: ..."/"Black: ..." for
    a spectator (viewer_color is None, since they play no side) - plus
    the room id centered, if this game came from one, and a Resign
    button in the reserved left strip while a real player's game is
    still live (show_resign_button - never true for a spectator or
    once game_over, see render_frame). For a player, "You: ..." is
    drawn over whichever side (left/right) their own color's side
    panel lives on - see renderer.py's White-left/Black-right side
    panels - rather than always on the left, so it's never mistaken
    for sitting above the opponent's panel. Caller must have already
    sized canvas with at least TOP_BANNER_HEIGHT of room at the top."""
    canvas.draw_rect(0, 0, width, TOP_BANNER_HEIGHT, TOP_BANNER_COLOR_BGRA, -1)
    text_y = TOP_BANNER_HEIGHT // 2 + 6

    if viewer_color is None:
        left_text = f"White: {white_player.username} ({white_player.rating})"
        right_text = f"Black: {black_player.username} ({black_player.rating})"
        left_color = _TEXT_COLOR_BGRA
        right_color = _TEXT_COLOR_BGRA
        left_text_x = TOP_BANNER_PADDING_X
    else:
        your_player = white_player if viewer_color == WHITE else black_player
        opponent_player = black_player if viewer_color == WHITE else white_player
        you_text = f"You: {your_player.username} ({your_player.rating})"
        opponent_text = f"{opponent_player.username} ({opponent_player.rating})"
        if viewer_color == WHITE:
            left_text, right_text = you_text, opponent_text
            left_color, right_color = TOP_BANNER_ACCENT_COLOR_BGRA, _TEXT_COLOR_BGRA
        else:
            left_text, right_text = opponent_text, you_text
            left_color, right_color = _TEXT_COLOR_BGRA, TOP_BANNER_ACCENT_COLOR_BGRA
        # Reserved even when show_resign_button is False (e.g. after
        # game_over) so this text doesn't visibly jump left the moment
        # the button disappears. The Resign button itself always lives
        # in this same left strip regardless of viewer_color - it's a
        # control, not an identity label.
        left_text_x = _RESIGN_RESERVED_WIDTH
        if show_resign_button:
            button_x, button_y, button_w, button_h = resign_button_rect(width, TOP_BANNER_HEIGHT)
            canvas.draw_rect(button_x, button_y, button_w, button_h, RESIGN_BUTTON_COLOR_BGRA, -1)
            canvas.draw_rect(button_x, button_y, button_w, button_h, RESIGN_BUTTON_BORDER_COLOR_BGRA, RESIGN_BUTTON_BORDER_THICKNESS)
            resign_text_w, resign_text_h = canvas.text_size(RESIGN_BUTTON_TEXT, RESIGN_BUTTON_FONT_SIZE, RESIGN_BUTTON_TEXT_THICKNESS)
            canvas.put_text(
                RESIGN_BUTTON_TEXT, button_x + button_w // 2 - resign_text_w // 2, button_y + button_h // 2 + resign_text_h // 2,
                RESIGN_BUTTON_FONT_SIZE, _TEXT_COLOR_BGRA, RESIGN_BUTTON_TEXT_THICKNESS,
            )

    canvas.put_text(left_text, left_text_x, text_y, TOP_BANNER_FONT_SIZE, left_color, TOP_BANNER_TEXT_THICKNESS)
    right_text_w, _ = canvas.text_size(right_text, TOP_BANNER_FONT_SIZE, TOP_BANNER_TEXT_THICKNESS)
    canvas.put_text(
        right_text, width - right_text_w - TOP_BANNER_PADDING_X, text_y,
        TOP_BANNER_FONT_SIZE, right_color, TOP_BANNER_TEXT_THICKNESS,
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


# One handler per ClientState.phase, dispatched through _PHASE_SCREENS
# below instead of a growing if/elif chain - the same pattern used for
# the client's click/key dispatch (input_controller.py's
# _CLICK_HANDLERS/_KEY_PRESS_HANDLERS, network_client_view.py's
# _SENTINEL_HANDLERS), just applied to "what to draw" instead of "what
# message to send". Every handler shares the same signature so the
# table stays uniform, even though most ignore cell_size/piece_set/
# renderer - only _render_matched_or_spectating (an actual board) needs
# those.
def _render_skin_menu(state: ClientState, width: int, height: int, cell_size: int, piece_set: str, renderer: Renderer) -> Img:
    return skin_menu_screen(width, height)


def _render_login_entry(state: ClientState, width: int, height: int, cell_size: int, piece_set: str, renderer: Renderer) -> Img:
    return login_entry_screen(width, height, state)


def _render_lobby(state: ClientState, width: int, height: int, cell_size: int, piece_set: str, renderer: Renderer) -> Img:
    return lobby_screen(width, height, state.rating)


def _render_no_opponent(state: ClientState, width: int, height: int, cell_size: int, piece_set: str, renderer: Renderer) -> Img:
    return lobby_screen(width, height, state.rating, message=NO_OPPONENT_TEXT)


def _render_room_action_failed(state: ClientState, width: int, height: int, cell_size: int, piece_set: str, renderer: Renderer) -> Img:
    verb = "create" if state.room_action_failure_kind == RoomAction.CREATE else "join"
    return lobby_screen(width, height, state.rating, message=f"Could not {verb} room: {state.room_action_failure_reason}")


def _render_room_create_entry(state: ClientState, width: int, height: int, cell_size: int, piece_set: str, renderer: Renderer) -> Img:
    return text_entry_screen(width, height, CREATE_ROOM_ENTRY_TITLE, state.text_entry_value)


def _render_room_join_entry(state: ClientState, width: int, height: int, cell_size: int, piece_set: str, renderer: Renderer) -> Img:
    return text_entry_screen(width, height, JOIN_ROOM_ENTRY_TITLE, state.text_entry_value)


def _render_room_pending_ack(state: ClientState, width: int, height: int, cell_size: int, piece_set: str, renderer: Renderer) -> Img:
    text = "Creating room..." if state.pending_room_action == "create" else "Joining room..."
    return text_screen(width, height, text)


def _render_room_waiting(state: ClientState, width: int, height: int, cell_size: int, piece_set: str, renderer: Renderer) -> Img:
    return room_pending_screen(width, height, state.room_id, state.rating)


def _render_waiting(state: ClientState, width: int, height: int, cell_size: int, piece_set: str, renderer: Renderer) -> Img:
    return waiting_screen(width, height, state.rating)


def _render_disconnected(state: ClientState, width: int, height: int, cell_size: int, piece_set: str, renderer: Renderer) -> Img:
    return text_screen(width, height, DISCONNECTED_TEXT)


def _render_matched_or_spectating(state: ClientState, width: int, height: int, cell_size: int, piece_set: str, renderer: Renderer) -> Img:
    """Shared by "matched" and "spectating" - the only two phases that
    ever show an actual board. Unlike every other phase above, this one
    isn't a single fixed screen - it still needs its own sequential
    guards (starting countdown, opponent-disconnect countdown, no
    view_state yet) before it can draw the board itself."""
    starting_remaining_s = (
        STARTING_DURATION_S - (time.perf_counter() - state.matched_at)
        if state.matched_at is not None else None
    )
    if starting_remaining_s is not None and starting_remaining_s > 0:
        return text_screen(width, height, starting_text(state.color, starting_remaining_s))

    disconnect_remaining_s = (
        state.opponent_disconnect_grace_seconds - (time.perf_counter() - state.opponent_disconnected_at)
        if state.opponent_disconnected_at is not None else None
    )
    if disconnect_remaining_s is not None and disconnect_remaining_s > 0:
        return text_screen(width, height, disconnect_text(disconnect_remaining_s))

    if state.view_state is None:
        return text_screen(width, height, LOGGING_IN_TEXT)

    game_over_progress = 1.0
    if state.game_over_started_at is not None:
        elapsed_s = time.perf_counter() - state.game_over_started_at
        game_over_progress = min(1.0, elapsed_s / GAME_OVER_FADE_DURATION_S)
    effective_view_state = apply_pending_motions(state.view_state, state.pending_motions, time.perf_counter())
    board_canvas = renderer.draw(
        effective_view_state, cell_size, piece_set,
        selected_position=state.selected_pos,
        legal_destinations=state.legal_destinations,
        invalid_target=state.invalid_target,
        game_over_progress=game_over_progress,
        show_back_to_lobby_button=True,  # this is the networked client - unlike image_view.py's offline game, there's always a lobby to go back to
    )

    board_height_px, board_width_px = board_canvas.img.shape[:2]
    canvas = Img()
    canvas.img = np.full((board_height_px + TOP_BANNER_HEIGHT, board_width_px, 4), _BACKGROUND_COLOR_BGRA, dtype=np.uint8)
    board_canvas.draw_on(canvas, 0, TOP_BANNER_HEIGHT)
    if state.white_player is not None and state.black_player is not None:
        _draw_top_banner(
            canvas, board_width_px, state.white_player, state.black_player, state.color, state.room_id,
            show_resign_button=state.color is not None and not state.view_state.game_over,
        )
    return canvas


_PHASE_SCREENS: Dict[Phase, Callable[[ClientState, int, int, int, str, Renderer], Img]] = {
    Phase.SKIN_MENU: _render_skin_menu,
    Phase.LOGIN_ENTRY: _render_login_entry,
    Phase.LOBBY: _render_lobby,
    Phase.NO_OPPONENT: _render_no_opponent,
    Phase.ROOM_ACTION_FAILED: _render_room_action_failed,
    Phase.ROOM_CREATE_ENTRY: _render_room_create_entry,
    Phase.ROOM_JOIN_ENTRY: _render_room_join_entry,
    Phase.ROOM_PENDING_ACK: _render_room_pending_ack,
    Phase.ROOM_WAITING: _render_room_waiting,
    Phase.WAITING: _render_waiting,
    Phase.DISCONNECTED: _render_disconnected,
    Phase.MATCHED: _render_matched_or_spectating,
    Phase.SPECTATING: _render_matched_or_spectating,
}


def render_frame(state: ClientState, cell_size: int, piece_set: str, renderer: Renderer) -> Img:
    """The single entry point run_client's loop calls every frame -
    decides which screen the current phase calls for and builds it, by
    dispatching through _PHASE_SCREENS. Pure given (state, cell_size,
    piece_set, renderer) - no I/O, so it's independently testable
    without a real window/network. Any phase with no entry in
    _PHASE_SCREENS (currently just "connecting") shows LOGGING_IN_TEXT -
    there's nothing more specific to draw yet."""
    width, height = screen_size(cell_size)
    handler = _PHASE_SCREENS.get(state.phase)
    if handler is None:
        return text_screen(width, height, LOGGING_IN_TEXT)
    return handler(state, width, height, cell_size, piece_set, renderer)

import numpy as np

from kungfu_chess.client.client_state import ClientState, PlayerInfo
from kungfu_chess.model.piece import BLACK, WHITE
from kungfu_chess.view.img import Img
from kungfu_chess.view.network_presentation import (
    TOP_BANNER_HEIGHT,
    _draw_top_banner,
    create_room_button_rect,
    disconnect_text,
    join_room_button_rect,
    play_button_rect,
    render_frame,
    room_pending_cancel_button_rect,
    room_pending_screen,
    screen_size,
    starting_text,
    text_entry_screen,
)
from kungfu_chess.view.renderer import Renderer

CELL_SIZE = 60

SCREEN_WIDTH, SCREEN_HEIGHT = 744, 480
_WHITE_PLAYER = PlayerInfo(username="alice", rating=1200)
_BLACK_PLAYER = PlayerInfo(username="bob", rating=1216)


def _banner_canvas() -> Img:
    canvas = Img()
    canvas.img = np.zeros((TOP_BANNER_HEIGHT, SCREEN_WIDTH, 4), dtype=np.uint8)
    return canvas


def test_starting_text_counts_down_before_go():
    assert starting_text(WHITE, remaining_s=2.5) == "You are White - starting in 3..."


def test_starting_text_shows_go_once_time_is_up():
    assert starting_text(WHITE, remaining_s=0.0) == "You are White - GO!"
    assert starting_text(WHITE, remaining_s=-0.5) == "You are White - GO!"


def test_starting_text_omits_the_color_prefix_when_color_is_unknown():
    assert starting_text(None, remaining_s=1.0) == "starting in 2..."


def test_disconnect_text_counts_down_before_resigning():
    assert disconnect_text(remaining_s=5.5) == "Opponent disconnected - auto-resign in 6..."


def test_disconnect_text_shows_resigning_once_time_is_up():
    assert disconnect_text(remaining_s=0.0) == "Opponent disconnected - resigning..."
    assert disconnect_text(remaining_s=-1.0) == "Opponent disconnected - resigning..."


def test_create_and_join_room_buttons_are_distinct_and_stacked_below_play():
    play_x, play_y, play_w, play_h = play_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)
    create_x, create_y, create_w, create_h = create_room_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)
    join_x, join_y, join_w, join_h = join_room_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)

    assert (create_x, create_y, create_w, create_h) != (play_x, play_y, play_w, play_h)
    assert (join_x, join_y, join_w, join_h) != (create_x, create_y, create_w, create_h)
    assert create_y >= play_y + play_h  # Create Room doesn't overlap Play above it
    assert join_y >= create_y + create_h  # Join Room doesn't overlap Create Room above it


def test_room_pending_screen_has_the_expected_canvas_size():
    canvas = room_pending_screen(SCREEN_WIDTH, SCREEN_HEIGHT, "ABC123", rating=1200)

    height_px, width_px = canvas.img.shape[:2]
    assert (width_px, height_px) == (SCREEN_WIDTH, SCREEN_HEIGHT)


def test_room_pending_cancel_button_rect_fits_within_the_screen():
    x, y, w, h = room_pending_cancel_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)

    assert 0 <= x and x + w <= SCREEN_WIDTH
    assert 0 <= y and y + h <= SCREEN_HEIGHT


def test_text_entry_screen_has_the_expected_canvas_size():
    canvas = text_entry_screen(SCREEN_WIDTH, SCREEN_HEIGHT, "Choose a room name:", "efrat")

    height_px, width_px = canvas.img.shape[:2]
    assert (width_px, height_px) == (SCREEN_WIDTH, SCREEN_HEIGHT)


def test_text_entry_screen_looks_different_as_the_typed_value_changes():
    empty = text_entry_screen(SCREEN_WIDTH, SCREEN_HEIGHT, "Choose a room name:", "")
    typed = text_entry_screen(SCREEN_WIDTH, SCREEN_HEIGHT, "Choose a room name:", "efrat-room")

    assert not np.array_equal(empty.img, typed.img)


def test_render_frame_room_create_entry_matches_text_entry_screen_size():
    state = ClientState(phase="room_create_entry", text_entry_value="efrat")
    canvas = render_frame(state, CELL_SIZE, "pieces3", Renderer())

    width, height = screen_size(CELL_SIZE)
    assert canvas.img.shape[:2] == text_entry_screen(width, height, "", "").img.shape[:2]


def test_render_frame_room_join_entry_does_not_crash():
    state = ClientState(phase="room_join_entry", text_entry_value="efrat")
    render_frame(state, CELL_SIZE, "pieces3", Renderer())  # must not raise


def test_render_frame_room_pending_ack_shows_a_distinct_screen_per_action():
    creating = render_frame(ClientState(phase="room_pending_ack", pending_room_action="create"), CELL_SIZE, "pieces3", Renderer())
    joining = render_frame(ClientState(phase="room_pending_ack", pending_room_action="join"), CELL_SIZE, "pieces3", Renderer())

    assert not np.array_equal(creating.img, joining.img)


def test_render_frame_room_action_failed_mentions_create_or_join():
    create_failed = render_frame(
        ClientState(phase="room_action_failed", room_action_failure_reason="room_name_taken", room_action_failure_kind="create"),
        CELL_SIZE, "pieces3", Renderer(),
    )
    join_failed = render_frame(
        ClientState(phase="room_action_failed", room_action_failure_reason="room_not_found", room_action_failure_kind="join"),
        CELL_SIZE, "pieces3", Renderer(),
    )

    assert not np.array_equal(create_failed.img, join_failed.img)


def test_top_banner_looks_different_for_a_player_than_for_a_spectator():
    """viewer_color=WHITE draws "You: ..."; viewer_color=None (a
    spectator) draws "White: .../Black: ..." instead - different text,
    so the rendered pixels must differ."""
    player_view = _banner_canvas()
    _draw_top_banner(player_view, SCREEN_WIDTH, _WHITE_PLAYER, _BLACK_PLAYER, viewer_color=WHITE)

    spectator_view = _banner_canvas()
    _draw_top_banner(spectator_view, SCREEN_WIDTH, _WHITE_PLAYER, _BLACK_PLAYER, viewer_color=None)

    assert not np.array_equal(player_view.img, spectator_view.img)


def test_top_banner_shows_the_room_id_when_present():
    without_room_id = _banner_canvas()
    _draw_top_banner(without_room_id, SCREEN_WIDTH, _WHITE_PLAYER, _BLACK_PLAYER, viewer_color=WHITE)

    with_room_id = _banner_canvas()
    _draw_top_banner(with_room_id, SCREEN_WIDTH, _WHITE_PLAYER, _BLACK_PLAYER, viewer_color=WHITE, room_id="ABC123")

    assert not np.array_equal(without_room_id.img, with_room_id.img)


def test_top_banner_labels_both_sides_by_color_for_a_spectator():
    black_viewer = _banner_canvas()
    _draw_top_banner(black_viewer, SCREEN_WIDTH, _WHITE_PLAYER, _BLACK_PLAYER, viewer_color=BLACK)

    spectator_view = _banner_canvas()
    _draw_top_banner(spectator_view, SCREEN_WIDTH, _WHITE_PLAYER, _BLACK_PLAYER, viewer_color=None)

    # A spectator's banner doesn't depend on any particular color's
    # point of view, unlike a real player's - confirms it takes its own,
    # third code path rather than accidentally aliasing WHITE's or BLACK's.
    assert not np.array_equal(black_viewer.img, spectator_view.img)

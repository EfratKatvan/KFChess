import time

from kungfu_chess.client.client_state import ClientState
from kungfu_chess.client.input_controller import decide_message
from kungfu_chess.engine.board_view_state import BoardViewState
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.model.board import Board
from kungfu_chess.model.position import Position
from kungfu_chess.server.messages import JumpMessage, RestartMessage, SeekGameMessage, SelectOrMoveMessage
from kungfu_chess.view.network_presentation import TOP_BANNER_HEIGHT, play_button_rect
from kungfu_chess.view.renderer import game_over_button_rect

CELL_SIZE = 100
SCREEN_WIDTH, SCREEN_HEIGHT = 800, 800


def _mapper():
    return BoardMapper(Board(width=8, height=8), cell_size=CELL_SIZE, y_offset=TOP_BANNER_HEIGHT)


def _decide(state, is_left_click=False, is_right_click=False, x=0, y=0, mapper=None):
    return decide_message(
        state, is_left_click, is_right_click, x, y,
        mapper or _mapper(), CELL_SIZE, SCREEN_WIDTH, SCREEN_HEIGHT,
    )


def test_lobby_click_inside_play_button_sends_seek_game():
    x, y, w, h = play_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)
    state = ClientState(phase="lobby")

    message = _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2)

    assert isinstance(message, SeekGameMessage)


def test_lobby_click_outside_play_button_sends_nothing():
    state = ClientState(phase="lobby")

    assert _decide(state, is_left_click=True, x=0, y=0) is None


def test_no_opponent_phase_also_accepts_the_play_button():
    x, y, w, h = play_button_rect(SCREEN_WIDTH, SCREEN_HEIGHT)
    state = ClientState(phase="no_opponent")

    message = _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2)

    assert isinstance(message, SeekGameMessage)


def test_click_before_matched_sends_nothing():
    state = ClientState(phase="waiting")

    assert _decide(state, is_left_click=True, x=150, y=150) is None


def test_click_during_the_starting_countdown_is_ignored():
    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state = ClientState(phase="matched", view_state=board, matched_at=time.perf_counter())

    assert _decide(state, is_left_click=True, x=150, y=150 + TOP_BANNER_HEIGHT) is None


def test_click_while_opponent_is_disconnected_is_ignored():
    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state = ClientState(
        phase="matched", view_state=board, matched_at=0.0,
        opponent_disconnected_at=time.perf_counter(), opponent_disconnect_grace_seconds=20,
    )

    assert _decide(state, is_left_click=True, x=150, y=150 + TOP_BANNER_HEIGHT) is None


def test_left_click_on_a_cell_sends_select_or_move():
    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state = ClientState(phase="matched", view_state=board, matched_at=0.0)

    message = _decide(state, is_left_click=True, x=50, y=50 + TOP_BANNER_HEIGHT)

    assert message == SelectOrMoveMessage(row=0, col=0)


def test_right_click_on_a_cell_sends_jump():
    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state = ClientState(phase="matched", view_state=board, matched_at=0.0)

    message = _decide(state, is_right_click=True, x=50, y=50 + TOP_BANNER_HEIGHT)

    assert message == JumpMessage(row=0, col=0)


def test_click_outside_the_board_bounds_sends_nothing():
    board = BoardViewState(width=8, height=8, game_over=False, pieces=())
    state = ClientState(phase="matched", view_state=board, matched_at=0.0)

    assert _decide(state, is_left_click=True, x=-50, y=50 + TOP_BANNER_HEIGHT) is None


def test_click_on_the_restart_button_after_game_over_sends_restart():
    board = BoardViewState(width=8, height=8, game_over=True, pieces=())
    state = ClientState(phase="matched", view_state=board, matched_at=0.0)
    x, y, w, h = game_over_button_rect(8, 8, CELL_SIZE)

    message = _decide(state, is_left_click=True, x=x + w // 2, y=y + h // 2 + TOP_BANNER_HEIGHT)

    assert isinstance(message, RestartMessage)


def test_click_elsewhere_after_game_over_sends_nothing():
    board = BoardViewState(width=8, height=8, game_over=True, pieces=())
    state = ClientState(phase="matched", view_state=board, matched_at=0.0)

    assert _decide(state, is_left_click=True, x=0, y=TOP_BANNER_HEIGHT) is None

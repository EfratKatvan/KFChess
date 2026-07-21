from kungfu_chess.model.piece import WHITE
from kungfu_chess.view.network_presentation import disconnect_text, starting_text


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

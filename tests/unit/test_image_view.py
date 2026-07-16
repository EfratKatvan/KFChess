from kungfu_chess.input.board_mapper import CELL_SIZE
from kungfu_chess.view.image_view import _MIN_CELL_SIZE, _SCREEN_FIT_FRACTION, compute_cell_size
from kungfu_chess.view.renderer import SIDE_PANEL_WIDTH


def test_compute_cell_size_falls_back_to_the_default_when_resolution_is_unknown():
    assert compute_cell_size(8, 8, screen_size=lambda: (None, None)) == CELL_SIZE


def test_compute_cell_size_fits_the_board_and_panels_within_the_screen_fraction():
    screen_width, screen_height = 1920, 1080
    cell_size = compute_cell_size(8, 8, screen_size=lambda: (screen_width, screen_height))

    panel_width_in_cells = SIDE_PANEL_WIDTH / CELL_SIZE
    total_width_px = cell_size * (8 + 2 * panel_width_in_cells)
    total_height_px = cell_size * 8

    # cell_size is a single rounded integer, so the fit can overshoot by at
    # most ~half a cell per row/column - a small, rounding-safe tolerance,
    # not a loophole: it should still be nowhere near double the screen.
    tolerance = 10
    assert total_width_px <= screen_width * _SCREEN_FIT_FRACTION + tolerance
    assert total_height_px <= screen_height * _SCREEN_FIT_FRACTION + tolerance


def test_compute_cell_size_shrinks_for_a_small_screen():
    small = compute_cell_size(8, 8, screen_size=lambda: (600, 400))
    large = compute_cell_size(8, 8, screen_size=lambda: (3840, 2160))

    assert small < large


def test_compute_cell_size_never_goes_below_the_minimum():
    tiny_cell_size = compute_cell_size(8, 8, screen_size=lambda: (100, 100))
    assert tiny_cell_size == _MIN_CELL_SIZE


def test_compute_cell_size_is_limited_by_whichever_dimension_is_tighter():
    # A very wide-but-short screen should be height-limited, not width-limited.
    wide_short = compute_cell_size(8, 8, screen_size=lambda: (10_000, 400))
    assert wide_short == compute_cell_size(1, 8, screen_size=lambda: (10_000, 400))

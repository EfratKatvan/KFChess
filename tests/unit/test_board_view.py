from kungfu_chess.model.position import Position
from kungfu_chess.view.board_view import BoardView


def test_cell_to_pixel_uses_col_for_x_and_row_for_y():
    assert BoardView.cell_to_pixel(Position(row=2, col=3), cell_size=100) == (300, 200)


def test_lerp_pixel_halfway_between_two_cells():
    source = Position(row=0, col=0)
    destination = Position(row=0, col=2)
    assert BoardView.lerp_pixel(source, destination, progress=0.5, cell_size=100) == (100, 0)


def test_lerp_pixel_at_progress_zero_and_one_matches_the_endpoints():
    source = Position(row=1, col=0)
    destination = Position(row=1, col=4)
    assert BoardView.lerp_pixel(source, destination, progress=0.0, cell_size=100) == (0, 100)
    assert BoardView.lerp_pixel(source, destination, progress=1.0, cell_size=100) == (400, 100)


def test_new_canvas_is_sized_to_the_board_in_pixels():
    board_view = BoardView()
    canvas = board_view.new_canvas(board_width=2, board_height=3, cell_size=100)
    height, width = canvas.img.shape[:2]
    assert (width, height) == (200, 300)


def test_new_canvas_returns_an_independent_copy_each_time():
    """אחרת ציור כלים על קנבס אחד היה 'מזהם' את הרקע הממוזכר לפריימים הבאים."""
    board_view = BoardView()
    first = board_view.new_canvas(board_width=1, board_height=1, cell_size=100)
    first.img[0, 0] = (1, 2, 3, 4)

    second = board_view.new_canvas(board_width=1, board_height=1, cell_size=100)

    assert tuple(second.img[0, 0]) != (1, 2, 3, 4)


def test_two_separate_board_views_do_not_share_cached_background():
    first_view = BoardView()
    second_view = BoardView()
    first_view.new_canvas(board_width=1, board_height=1, cell_size=100)
    assert second_view._backgrounds == {}

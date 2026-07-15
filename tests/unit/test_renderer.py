from kungfu_chess.assets_config import PIECE_SETS, asset_code
from kungfu_chess.engine.board_view_state import BoardViewState, PieceView
from kungfu_chess.model.piece import WHITE, BLACK, ROOK, KING, PAWN, QUEEN
from kungfu_chess.model.position import Position
from kungfu_chess.view.renderer import Renderer


def make_piece_view(color, kind, row, col, visual_state="idle", elapsed_ms=0, **kwargs):
    return PieceView(
        position=Position(row, col), color=color, kind=kind,
        visual_state=visual_state, elapsed_ms=elapsed_ms, **kwargs,
    )


def test_asset_code_converts_color_kind_to_ctd26_order():
    assert asset_code(WHITE, PAWN) == "PW"
    assert asset_code(BLACK, KING) == "KB"


def test_draw_returns_a_canvas_sized_to_the_board_in_pixels():
    view_state = BoardViewState(width=2, height=3, game_over=False, pieces=(make_piece_view(WHITE, ROOK, 0, 0),))

    canvas = Renderer().draw(view_state, cell_size=100)

    height, width = canvas.img.shape[:2]
    assert (width, height) == (200, 300)


def test_draw_accepts_either_piece_set():
    view_state = BoardViewState(width=1, height=1, game_over=False, pieces=(make_piece_view(WHITE, QUEEN, 0, 0),))
    renderer = Renderer()

    for piece_set in PIECE_SETS:
        canvas = renderer.draw(view_state, cell_size=100, piece_set=piece_set)
        assert canvas.img is not None


def test_draw_reuses_injected_caches_across_calls():
    """שני Renderer עם אותם cache מוזרק חולקים אנימציות טעונות; שני
    Renderer בלי הזרקה (ברירת מחדל) לא."""
    from kungfu_chess.view.animation import AnimationCache
    from kungfu_chess.view.board_view import BoardView

    shared_cache = AnimationCache()
    shared_board_view = BoardView()
    view_state = BoardViewState(width=1, height=1, game_over=False, pieces=(make_piece_view(WHITE, ROOK, 0, 0),))

    Renderer(animation_cache=shared_cache, board_view=shared_board_view).draw(view_state, cell_size=100)

    assert len(shared_cache._animations) == 1
    assert len(shared_board_view._backgrounds) == 1


def test_draw_interpolates_pixel_position_for_a_moving_piece():
    moving = make_piece_view(
        WHITE, ROOK, 0, 0, visual_state="move", elapsed_ms=333,
        target_position=Position(0, 2), progress=0.5,
    )
    view_state = BoardViewState(width=3, height=1, game_over=False, pieces=(moving,))

    canvas = Renderer().draw(view_state, cell_size=100)

    assert canvas.img is not None  # draw_on would raise ValueError if the pixel math went out of bounds


def test_draw_cooldown_overlay_paints_the_whole_cell_at_full_remaining_fraction():
    import numpy as np

    from kungfu_chess.view.img import Img
    from kungfu_chess.view.renderer import _draw_cooldown_overlay

    canvas = Img()
    canvas.img = np.zeros((100, 100, 4), dtype=np.uint8)
    canvas.img[..., 3] = 255

    _draw_cooldown_overlay(canvas, pixel_pos=(0, 0), remaining_fraction=1.0, cell_size=100)

    assert tuple(canvas.img[0, 0][:3]) != (0, 0, 0)
    assert tuple(canvas.img[99, 0][:3]) != (0, 0, 0)


def test_draw_cooldown_overlay_drains_from_the_top_as_the_fraction_decreases():
    import numpy as np

    from kungfu_chess.view.img import Img
    from kungfu_chess.view.renderer import _draw_cooldown_overlay

    canvas = Img()
    canvas.img = np.zeros((100, 100, 4), dtype=np.uint8)
    canvas.img[..., 3] = 255

    _draw_cooldown_overlay(canvas, pixel_pos=(0, 0), remaining_fraction=0.5, cell_size=100)

    assert tuple(canvas.img[0, 0][:3]) == (0, 0, 0)   # top half: already drained/untouched
    assert tuple(canvas.img[99, 0][:3]) != (0, 0, 0)  # bottom half: "sand" still pooled there


def test_draw_cooldown_overlay_draws_nothing_once_the_cooldown_is_over():
    import numpy as np

    from kungfu_chess.view.img import Img
    from kungfu_chess.view.renderer import _draw_cooldown_overlay

    canvas = Img()
    canvas.img = np.zeros((100, 100, 4), dtype=np.uint8)
    canvas.img[..., 3] = 255

    _draw_cooldown_overlay(canvas, pixel_pos=(0, 0), remaining_fraction=0.0, cell_size=100)

    assert (canvas.img[..., :3] == 0).all()


def test_draw_does_not_crash_for_a_piece_that_is_cooling_down():
    """טסט אינטגרציה: ה-Renderer בפועל מפעיל את ה-overlay דרך draw(), לא
    רק דרך הבדיקות הישירות של _draw_cooldown_overlay למעלה."""
    cooling = make_piece_view(WHITE, ROOK, 0, 0, visual_state="short_rest", remaining_fraction=1.0)
    view_state = BoardViewState(width=1, height=1, game_over=False, pieces=(cooling,))

    canvas = Renderer().draw(view_state, cell_size=100)

    assert canvas.img is not None


def test_draw_highlights_the_selected_cell():
    import numpy as np

    from kungfu_chess.view.renderer import SELECTION_HIGHLIGHT_COLOR_BGRA

    view_state = BoardViewState(width=2, height=1, game_over=False, pieces=())

    canvas = Renderer().draw(view_state, cell_size=100, selected_position=Position(0, 1))

    # top-left border pixel of the selected cell (0,1), at pixel (x=100, y=0)
    assert tuple(canvas.img[0, 100]) == SELECTION_HIGHLIGHT_COLOR_BGRA
    # deep in the interior of the non-selected cell (0,0) - never painted by the border
    assert tuple(canvas.img[50, 50]) != SELECTION_HIGHLIGHT_COLOR_BGRA


def test_draw_does_not_highlight_anything_when_no_cell_is_selected():
    import numpy as np

    from kungfu_chess.view.renderer import SELECTION_HIGHLIGHT_COLOR_BGRA

    view_state = BoardViewState(width=1, height=1, game_over=False, pieces=())

    canvas = Renderer().draw(view_state, cell_size=100, selected_position=None)

    highlight = np.array(SELECTION_HIGHLIGHT_COLOR_BGRA, dtype=canvas.img.dtype)
    assert not np.any(np.all(canvas.img == highlight, axis=-1))


def test_draw_marks_legal_destination_cells():
    import numpy as np

    from kungfu_chess.view.renderer import DESTINATION_MARKER_COLOR_BGRA

    view_state = BoardViewState(width=2, height=1, game_over=False, pieces=())

    canvas = Renderer().draw(view_state, cell_size=100, legal_destinations=[Position(0, 1)])

    # center of the marked cell (0,1) -> painted with the marker color
    assert tuple(canvas.img[50, 150]) == DESTINATION_MARKER_COLOR_BGRA
    # center of the unmarked cell (0,0) -> not painted
    assert tuple(canvas.img[50, 50]) != DESTINATION_MARKER_COLOR_BGRA


def test_draw_marks_nothing_when_no_destinations_are_given():
    import numpy as np

    from kungfu_chess.view.renderer import DESTINATION_MARKER_COLOR_BGRA

    view_state = BoardViewState(width=1, height=1, game_over=False, pieces=())

    canvas = Renderer().draw(view_state, cell_size=100, legal_destinations=None)

    marker = np.array(DESTINATION_MARKER_COLOR_BGRA, dtype=canvas.img.dtype)
    assert not np.any(np.all(canvas.img == marker, axis=-1))

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


def test_draw_returns_a_canvas_sized_to_the_board_plus_the_side_panels():
    from kungfu_chess.view.renderer import SIDE_PANEL_WIDTH

    view_state = BoardViewState(width=2, height=3, game_over=False, pieces=(make_piece_view(WHITE, ROOK, 0, 0),))

    canvas = Renderer().draw(view_state, cell_size=100)

    height, width = canvas.img.shape[:2]
    assert (width, height) == (200 + 2 * SIDE_PANEL_WIDTH, 300)


def test_side_panel_width_for_scales_proportionally_with_cell_size():
    from kungfu_chess.view.renderer import SIDE_PANEL_WIDTH, side_panel_width_for
    from kungfu_chess.input.board_mapper import CELL_SIZE

    assert side_panel_width_for(CELL_SIZE) == SIDE_PANEL_WIDTH  # the reference size is a no-op
    assert side_panel_width_for(CELL_SIZE * 2) == SIDE_PANEL_WIDTH * 2
    assert side_panel_width_for(CELL_SIZE // 2) == SIDE_PANEL_WIDTH // 2


def test_draw_scales_the_canvas_and_panels_together_at_a_non_default_cell_size():
    from kungfu_chess.view.renderer import side_panel_width_for

    view_state = BoardViewState(width=2, height=2, game_over=False, pieces=())
    cell_size = 60

    canvas = Renderer().draw(view_state, cell_size=cell_size)

    height, width = canvas.img.shape[:2]
    expected_panel_width = side_panel_width_for(cell_size)
    assert (width, height) == (2 * cell_size + 2 * expected_panel_width, 2 * cell_size)


def test_draw_maps_a_piece_at_a_non_default_cell_size_into_the_shifted_board_area():
    """A regression guard for the click-mapping-gap bug class: a piece
    drawn at a scaled cell_size must land to the right of the (also
    scaled) side panel, not at some stale fixed offset."""
    from kungfu_chess.view.renderer import side_panel_width_for

    cell_size = 60
    piece = make_piece_view(WHITE, ROOK, 0, 0)
    view_state = BoardViewState(width=1, height=1, game_over=False, pieces=(piece,))

    canvas = Renderer().draw(view_state, cell_size=cell_size)

    panel_width = side_panel_width_for(cell_size)
    # the piece's own cell should not be blank/background-colored at its expected pixel origin
    assert tuple(canvas.img[cell_size // 2, panel_width + cell_size // 2]) != tuple(canvas.img[0, 0])


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

    from kungfu_chess.view.renderer import SIDE_PANEL_WIDTH, SELECTION_HIGHLIGHT_COLOR_BGRA

    view_state = BoardViewState(width=2, height=1, game_over=False, pieces=())

    canvas = Renderer().draw(view_state, cell_size=100, selected_position=Position(0, 1))

    # top-left border pixel of the selected cell (0,1) - shifted right by the left side panel
    assert tuple(canvas.img[0, SIDE_PANEL_WIDTH + 100]) == SELECTION_HIGHLIGHT_COLOR_BGRA
    # deep in the interior of the non-selected cell (0,0) - never painted by the border
    assert tuple(canvas.img[50, SIDE_PANEL_WIDTH + 50]) != SELECTION_HIGHLIGHT_COLOR_BGRA


def test_draw_does_not_highlight_anything_when_no_cell_is_selected():
    import numpy as np

    from kungfu_chess.view.renderer import SELECTION_HIGHLIGHT_COLOR_BGRA

    view_state = BoardViewState(width=1, height=1, game_over=False, pieces=())

    canvas = Renderer().draw(view_state, cell_size=100, selected_position=None)

    highlight = np.array(SELECTION_HIGHLIGHT_COLOR_BGRA, dtype=canvas.img.dtype)
    assert not np.any(np.all(canvas.img == highlight, axis=-1))


def test_draw_destination_highlight_tints_the_whole_cell():
    import numpy as np

    from kungfu_chess.view.img import Img
    from kungfu_chess.view.renderer import _draw_destination_highlight

    canvas = Img()
    canvas.img = np.zeros((100, 100, 4), dtype=np.uint8)
    canvas.img[..., 3] = 255

    _draw_destination_highlight(canvas, (0, 0), cell_size=100)

    assert tuple(canvas.img[0, 0][:3]) != (0, 0, 0)      # corner: tinted
    assert tuple(canvas.img[99, 99][:3]) != (0, 0, 0)    # opposite corner: also tinted (whole cell, not a dot)


def test_draw_marks_legal_destination_cells_by_tinting_them():
    from kungfu_chess.view.renderer import SIDE_PANEL_WIDTH

    view_state = BoardViewState(width=2, height=1, game_over=False, pieces=())

    baseline = Renderer().draw(view_state, cell_size=100, legal_destinations=None)
    highlighted = Renderer().draw(view_state, cell_size=100, legal_destinations=[Position(0, 1)])

    row = 50
    assert tuple(highlighted.img[row, SIDE_PANEL_WIDTH + 150]) != tuple(baseline.img[row, SIDE_PANEL_WIDTH + 150])  # marked cell: changed
    assert tuple(highlighted.img[row, SIDE_PANEL_WIDTH + 50]) == tuple(baseline.img[row, SIDE_PANEL_WIDTH + 50])    # other cell: untouched


def test_draw_marks_nothing_when_no_destinations_are_given():
    view_state = BoardViewState(width=1, height=1, game_over=False, pieces=())

    with_none = Renderer().draw(view_state, cell_size=100, legal_destinations=None)
    with_empty = Renderer().draw(view_state, cell_size=100, legal_destinations=[])

    assert (with_none.img == with_empty.img).all()


def test_draw_renders_different_side_panels_for_different_scores():
    no_score = BoardViewState(width=8, height=1, game_over=False, pieces=(), scores={WHITE: 0, BLACK: 0})
    with_score = BoardViewState(width=8, height=1, game_over=False, pieces=(), scores={WHITE: 9, BLACK: 3})

    canvas_no_score = Renderer().draw(no_score, cell_size=100)
    canvas_with_score = Renderer().draw(with_score, cell_size=100)

    # the two side panels (left+right) must differ - the score text is different
    assert not (canvas_no_score.img == canvas_with_score.img).all()


def test_draw_side_panels_default_scores_to_zero_when_missing():
    view_state = BoardViewState(width=1, height=1, game_over=False, pieces=())  # no scores passed

    canvas = Renderer().draw(view_state, cell_size=100)  # must not raise

    assert canvas.img is not None


def test_draw_destination_highlight_accepts_a_custom_color():
    import numpy as np

    from kungfu_chess.view.img import Img
    from kungfu_chess.view.renderer import _draw_destination_highlight, CAPTURE_HIGHLIGHT_COLOR_BGRA, DESTINATION_HIGHLIGHT_COLOR_BGRA

    green_canvas = Img()
    green_canvas.img = np.zeros((100, 100, 4), dtype=np.uint8)
    green_canvas.img[..., 3] = 255
    _draw_destination_highlight(green_canvas, (0, 0), cell_size=100)  # default color

    red_canvas = Img()
    red_canvas.img = np.zeros((100, 100, 4), dtype=np.uint8)
    red_canvas.img[..., 3] = 255
    _draw_destination_highlight(red_canvas, (0, 0), cell_size=100, color_bgra=CAPTURE_HIGHLIGHT_COLOR_BGRA)

    assert not (green_canvas.img == red_canvas.img).all()
    assert DESTINATION_HIGHLIGHT_COLOR_BGRA != CAPTURE_HIGHLIGHT_COLOR_BGRA


def test_draw_tints_a_capturable_destination_differently_than_an_empty_one():
    """Identical board (same attacker, same enemy pawn sitting on the
    requested destination) in both calls - the only difference is
    whether a piece is selected, which is what decides "capturable" in
    draw(). Comparing only the destination cell (0,1)'s own pixels -
    not (0,0), which also gets a selection border in the second call -
    isolates the highlight color from that unrelated difference."""
    import numpy as np

    from kungfu_chess.view.renderer import SIDE_PANEL_WIDTH

    attacker = make_piece_view(WHITE, ROOK, 0, 0)
    defender = make_piece_view(BLACK, PAWN, 0, 1)
    view_state = BoardViewState(width=2, height=1, game_over=False, pieces=(attacker, defender))

    canvas_unselected = Renderer().draw(view_state, cell_size=100, selected_position=None, legal_destinations=[Position(0, 1)])
    canvas_selected = Renderer().draw(view_state, cell_size=100, selected_position=Position(0, 0), legal_destinations=[Position(0, 1)])

    destination_cell = np.s_[0:100, SIDE_PANEL_WIDTH + 100:SIDE_PANEL_WIDTH + 200]
    assert not (canvas_unselected.img[destination_cell] == canvas_selected.img[destination_cell]).all()


def test_draw_highlights_an_invalid_target_in_red():
    from kungfu_chess.view.renderer import SIDE_PANEL_WIDTH, INVALID_TARGET_HIGHLIGHT_COLOR_BGRA

    view_state = BoardViewState(width=2, height=1, game_over=False, pieces=())

    canvas = Renderer().draw(view_state, cell_size=100, invalid_target=Position(0, 1))

    assert tuple(canvas.img[0, SIDE_PANEL_WIDTH + 100]) == INVALID_TARGET_HIGHLIGHT_COLOR_BGRA


def test_draw_does_not_highlight_an_invalid_target_when_there_is_none():
    from kungfu_chess.view.renderer import INVALID_TARGET_HIGHLIGHT_COLOR_BGRA
    import numpy as np

    view_state = BoardViewState(width=1, height=1, game_over=False, pieces=())

    canvas = Renderer().draw(view_state, cell_size=100, invalid_target=None)

    highlight = np.array(INVALID_TARGET_HIGHLIGHT_COLOR_BGRA, dtype=canvas.img.dtype)
    assert not np.any(np.all(canvas.img == highlight, axis=-1))


def test_draw_shows_a_game_over_overlay_once_the_game_ends():
    playing = BoardViewState(width=8, height=8, game_over=False, pieces=())
    ended = BoardViewState(width=8, height=8, game_over=True, pieces=())

    canvas_playing = Renderer().draw(playing, cell_size=100)
    canvas_ended = Renderer().draw(ended, cell_size=100)

    assert not (canvas_playing.img == canvas_ended.img).all()


def test_draw_with_a_partial_game_over_progress_only_shows_the_dimming_band():
    """game_over_progress < 1.0 (mid fade-in) should not yet paint the
    "GAME OVER" text/button - see network_client_view.py's fade-in
    animation, which starts at 0 the instant game_over turns True."""
    from kungfu_chess.view.renderer import game_over_button_rect

    view_state = BoardViewState(width=8, height=8, game_over=True, pieces=())

    mid_fade = Renderer().draw(view_state, cell_size=100, game_over_progress=0.3)
    full = Renderer().draw(view_state, cell_size=100, game_over_progress=1.0)

    x, y, width, height = game_over_button_rect(view_state.width, view_state.height, cell_size=100)
    button_border_pixel_mid_fade = tuple(mid_fade.img[y, x + width // 2])
    button_border_pixel_full = tuple(full.img[y, x + width // 2])

    assert button_border_pixel_mid_fade != button_border_pixel_full
    assert not (mid_fade.img == full.img).all()


def test_draw_with_zero_game_over_progress_still_shows_some_dimming():
    playing = BoardViewState(width=8, height=8, game_over=False, pieces=())
    just_ended = BoardViewState(width=8, height=8, game_over=True, pieces=())

    canvas_playing = Renderer().draw(playing, cell_size=100)
    canvas_just_ended = Renderer().draw(just_ended, cell_size=100, game_over_progress=0.0)

    assert (canvas_playing.img == canvas_just_ended.img).all()  # progress 0 - band fully transparent, no visible change yet


def test_game_over_button_rect_sits_inside_the_board_and_side_panels():
    """Regression guard for the HUD_HEIGHT-style bug: the button's
    geometry (used both to draw it and to hit-test clicks in
    image_view.py) must fall entirely within the actual canvas draw()
    produces for the same board_width/height/cell_size."""
    from kungfu_chess.view.renderer import game_over_button_rect

    view_state = BoardViewState(width=8, height=8, game_over=True, pieces=())
    canvas = Renderer().draw(view_state, cell_size=100)
    canvas_height, canvas_width = canvas.img.shape[:2]

    x, y, width, height = game_over_button_rect(view_state.width, view_state.height, cell_size=100)

    assert 0 <= x and x + width <= canvas_width
    assert 0 <= y and y + height <= canvas_height


def test_draw_paints_the_game_over_button_at_its_own_reported_rect():
    from kungfu_chess.view.renderer import game_over_button_rect, GAME_OVER_BUTTON_BORDER_COLOR_BGRA

    view_state = BoardViewState(width=8, height=8, game_over=True, pieces=())
    canvas = Renderer().draw(view_state, cell_size=100)

    x, y, width, height = game_over_button_rect(view_state.width, view_state.height, cell_size=100)
    border_pixel = tuple(canvas.img[y, x + width // 2])  # top edge of the border, mid-width

    assert border_pixel == GAME_OVER_BUTTON_BORDER_COLOR_BGRA


def test_draw_side_panel_renders_a_move_log_entry():
    from kungfu_chess.engine.board_view_state import MoveLogEntry
    from kungfu_chess.model.piece import WHITE, PAWN

    no_moves = BoardViewState(width=8, height=8, game_over=False, pieces=(), move_log={WHITE: ()})
    with_move = BoardViewState(
        width=8, height=8, game_over=False, pieces=(),
        move_log={WHITE: (MoveLogEntry(
            elapsed_ms=1000, from_pos=Position(6, 4), to_pos=Position(4, 4), kind=PAWN, is_capture=False,
        ),)},
    )

    canvas_no_moves = Renderer().draw(no_moves, cell_size=100)
    canvas_with_move = Renderer().draw(with_move, cell_size=100)

    assert not (canvas_no_moves.img == canvas_with_move.img).all()


def test_draw_shows_a_players_username_and_rating_on_their_side_panel():
    from kungfu_chess.view.renderer import PlayerInfo

    view_state = BoardViewState(width=8, height=8, game_over=False, pieces=())

    without_player = Renderer().draw(view_state, cell_size=100)
    with_player = Renderer().draw(view_state, cell_size=100, white_player=PlayerInfo(username="efrat", rating=1216))

    assert not (without_player.img == with_player.img).all()


def test_draw_marks_only_your_own_color_as_you():
    from kungfu_chess.model.piece import WHITE, BLACK
    from kungfu_chess.view.renderer import PlayerInfo

    view_state = BoardViewState(width=8, height=8, game_over=False, pieces=())
    white = PlayerInfo(username="efrat", rating=1216)
    black = PlayerInfo(username="eti", rating=1184)

    as_white = Renderer().draw(view_state, cell_size=100, white_player=white, black_player=black, your_color=WHITE)
    as_black = Renderer().draw(view_state, cell_size=100, white_player=white, black_player=black, your_color=BLACK)
    as_spectator = Renderer().draw(view_state, cell_size=100, white_player=white, black_player=black, your_color=None)

    # the "You" marker moves to a different panel depending on your_color, so all three canvases differ
    assert not (as_white.img == as_black.img).all()
    assert not (as_white.img == as_spectator.img).all()
    assert not (as_black.img == as_spectator.img).all()


def test_move_notation_formats_pawn_moves_without_a_piece_letter():
    from kungfu_chess.engine.board_view_state import MoveLogEntry
    from kungfu_chess.model.piece import PAWN
    from kungfu_chess.view.renderer import _move_notation

    quiet = MoveLogEntry(elapsed_ms=0, from_pos=Position(6, 4), to_pos=Position(4, 4), kind=PAWN, is_capture=False)
    capture = MoveLogEntry(elapsed_ms=0, from_pos=Position(4, 4), to_pos=Position(3, 3), kind=PAWN, is_capture=True)

    assert _move_notation(quiet, board_height=8) == "e2-e4"
    assert _move_notation(capture, board_height=8) == "e4xd5"


def test_move_notation_formats_piece_moves_with_a_letter():
    from kungfu_chess.engine.board_view_state import MoveLogEntry
    from kungfu_chess.model.piece import KNIGHT, QUEEN
    from kungfu_chess.view.renderer import _move_notation

    knight_move = MoveLogEntry(elapsed_ms=0, from_pos=Position(7, 6), to_pos=Position(5, 5), kind=KNIGHT, is_capture=False)
    queen_capture = MoveLogEntry(elapsed_ms=0, from_pos=Position(4, 4), to_pos=Position(0, 4), kind=QUEEN, is_capture=True)

    assert _move_notation(knight_move, board_height=8) == "Ng1-f3"
    assert _move_notation(queen_capture, board_height=8) == "Qe4xe8"

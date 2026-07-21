from kungfu_chess.model.game_state import MoveLoggedEvent, PieceCapturedEvent
from kungfu_chess.model.piece import WHITE, BLACK, PAWN, KNIGHT, QUEEN, ROOK
from kungfu_chess.model.position import Position
from kungfu_chess.events.observers import MoveLogObserver, ScoreObserver


def test_move_log_observer_starts_empty():
    observer = MoveLogObserver()
    assert observer.as_dict() == {WHITE: (), BLACK: ()}


def test_move_log_observer_accumulates_entries_per_color():
    observer = MoveLogObserver()

    observer.on_move_logged(MoveLoggedEvent(WHITE, Position(6, 4), Position(4, 4), PAWN, False, 0))
    observer.on_move_logged(MoveLoggedEvent(BLACK, Position(1, 4), Position(3, 4), PAWN, False, 1000))
    observer.on_move_logged(MoveLoggedEvent(WHITE, Position(7, 6), Position(5, 5), KNIGHT, False, 2000))

    result = observer.as_dict()

    assert len(result[WHITE]) == 2
    assert len(result[BLACK]) == 1
    assert result[WHITE][0].to_pos == Position(4, 4)
    assert result[WHITE][1].to_pos == Position(5, 5)
    assert result[BLACK][0].to_pos == Position(3, 4)


def test_move_log_observer_records_kind_and_capture_flag_from_the_event():
    observer = MoveLogObserver()

    observer.on_move_logged(MoveLoggedEvent(WHITE, Position(4, 4), Position(3, 3), PAWN, True, 500))

    [entry] = observer.as_dict()[WHITE]
    assert entry.kind == PAWN
    assert entry.is_capture is True
    assert entry.elapsed_ms == 500


def test_move_log_observer_as_dict_is_a_snapshot_not_a_live_reference():
    """Regression guard: as_dict() is read once per frame (see
    image_view.py) - if it returned a reference into the observer's own
    mutable list, a later move would silently retro-edit an
    already-handed-out BoardViewState."""
    observer = MoveLogObserver()
    observer.on_move_logged(MoveLoggedEvent(WHITE, Position(6, 4), Position(4, 4), PAWN, False, 0))

    first = observer.as_dict()
    observer.on_move_logged(MoveLoggedEvent(WHITE, Position(6, 3), Position(4, 3), PAWN, False, 1000))

    assert len(first[WHITE]) == 1


def test_score_observer_starts_at_zero_for_both_colors():
    observer = ScoreObserver()
    assert observer.as_dict() == {WHITE: 0, BLACK: 0}


def test_score_observer_accumulates_points_per_color():
    observer = ScoreObserver()

    observer.on_piece_captured(PieceCapturedEvent(WHITE, QUEEN, 9))
    observer.on_piece_captured(PieceCapturedEvent(WHITE, PAWN, 1))
    observer.on_piece_captured(PieceCapturedEvent(BLACK, ROOK, 5))

    assert observer.as_dict() == {WHITE: 10, BLACK: 5}


def test_score_observer_as_dict_is_a_snapshot_not_a_live_reference():
    observer = ScoreObserver()
    observer.on_piece_captured(PieceCapturedEvent(WHITE, QUEEN, 9))

    first = observer.as_dict()
    observer.on_piece_captured(PieceCapturedEvent(WHITE, PAWN, 1))

    assert first[WHITE] == 9

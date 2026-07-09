from kungfu_chess.model.position import Position


def test_positions_with_same_row_and_col_are_equal():
    assert Position(2, 3) == Position(2, 3)


def test_positions_with_different_row_are_not_equal():
    assert Position(2, 3) != Position(5, 3)


def test_positions_with_different_col_are_not_equal():
    assert Position(2, 3) != Position(2, 9)


def test_position_repr_is_readable():
    # דורש: כשלון assertion על Position יראה תוצאה קריאה (row/col גלויים ב-repr)
    assert repr(Position(2, 3)) == "Position(row=2, col=3)"


def test_position_is_hashable():
    # frozen=True -> אפשר להשתמש ב-Position כמפתח (יידרש כש-Board יחזיק מיפוי תא->כלי)
    positions = {Position(0, 0), Position(0, 0), Position(1, 1)}
    assert len(positions) == 2

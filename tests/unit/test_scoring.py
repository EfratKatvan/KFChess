from kungfu_chess.model.piece import BISHOP, KING, KNIGHT, PAWN, QUEEN, ROOK
from kungfu_chess.rules.scoring import piece_value


def test_piece_values_match_standard_chess_point_values():
    assert piece_value(PAWN) == 1
    assert piece_value(KNIGHT) == 3
    assert piece_value(BISHOP) == 3
    assert piece_value(ROOK) == 5
    assert piece_value(QUEEN) == 9
    assert piece_value(KING) == 0

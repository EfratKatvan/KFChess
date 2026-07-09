from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, WHITE, BLACK, ROOK, KING, IDLE, MOVING, CAPTURED


def test_piece_holds_its_fields():
    piece = Piece(id="w-rook-1", color=WHITE, kind=ROOK, cell=Position(0, 0))
    assert piece.id == "w-rook-1"
    assert piece.color == WHITE
    assert piece.kind == ROOK
    assert piece.cell == Position(0, 0)


def test_piece_defaults_to_idle_state():
    piece = Piece(id="b-king-1", color=BLACK, kind=KING, cell=Position(7, 4))
    assert piece.state == IDLE


def test_piece_cell_can_be_updated_when_it_moves():
    piece = Piece(id="w-rook-1", color=WHITE, kind=ROOK, cell=Position(0, 0))
    piece.cell = Position(0, 2)
    assert piece.cell == Position(0, 2)


def test_piece_state_can_change():
    piece = Piece(id="w-rook-1", color=WHITE, kind=ROOK, cell=Position(0, 0))
    piece.state = MOVING
    assert piece.state == MOVING
    piece.state = CAPTURED
    assert piece.state == CAPTURED


def test_two_pieces_with_same_color_and_kind_are_distinct_by_id():
    piece_a = Piece(id="w-rook-1", color=WHITE, kind=ROOK, cell=Position(0, 0))
    piece_b = Piece(id="w-rook-2", color=WHITE, kind=ROOK, cell=Position(0, 7))
    assert piece_a.id != piece_b.id
    assert piece_a != piece_b

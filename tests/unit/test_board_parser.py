import io as pyio
import pytest

from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import WHITE, BLACK, ROOK, KING
from kungfu_chess.io.board_parser import (
    read_input_lines,
    parse_board_section,
    parse_commands_section,
    validate_board,
    build_legal_tokens,
    token_to_piece,
    piece_to_token,
    build_board,
    BoardValidationError,
    ERROR_ROW_WIDTH_MISMATCH,
    ERROR_UNKNOWN_TOKEN,
)

LEGAL = build_legal_tokens()


# ==========================================
# token_to_piece / piece_to_token / build_board
# ==========================================

def test_token_to_piece_decodes_color_and_kind():
    piece = token_to_piece("wR", Position(0, 0))
    assert piece.color == WHITE
    assert piece.kind == ROOK
    assert piece.cell == Position(0, 0)


def test_token_to_piece_black_king():
    piece = token_to_piece("bK", Position(7, 4))
    assert piece.color == BLACK
    assert piece.kind == KING


def test_piece_to_token_is_the_inverse_of_token_to_piece():
    piece = token_to_piece("wQ", Position(1, 2))
    assert piece_to_token(piece) == "wQ"


def test_build_board_places_pieces_at_the_right_cells():
    board = build_board([["wK", ".", "bK"], [".", ".", "."]])
    assert board.width == 3
    assert board.height == 2
    assert board.piece_at(Position(0, 0)).color == WHITE
    assert board.piece_at(Position(0, 2)).color == BLACK
    assert board.piece_at(Position(1, 1)) is None


def test_build_board_on_empty_rows_gives_zero_dimensions():
    board = build_board([])
    assert board.width == 0
    assert board.height == 0


# ==========================================
# build_legal_tokens
# ==========================================

def test_includes_empty_cell():
    assert "." in build_legal_tokens()


def test_includes_all_color_piece_combinations():
    tokens = build_legal_tokens()
    for color in ("w", "b"):
        for piece in ("K", "Q", "R", "B", "N", "P"):
            assert f"{color}{piece}" in tokens


def test_excludes_invalid_token():
    assert "xX" not in build_legal_tokens()


def test_token_count_is_exact():
    assert len(build_legal_tokens()) == 13


# ==========================================
# read_input_lines / parse_board_section / parse_commands_section
# ==========================================

def test_read_input_lines_strips_whitespace():
    stream = pyio.StringIO("  Board:  \n wK . \n")
    lines = read_input_lines(stream)
    assert lines == ["Board:", "wK ."]


def test_parse_board_section_basic():
    lines = ["Board:", "wK . bK", "Commands:", "move x"]
    rows = parse_board_section(lines)
    assert rows == [["wK", ".", "bK"]]


def test_parse_board_section_multiple_rows():
    lines = ["Board:", ". . .", "wP wP wP", "Commands:"]
    rows = parse_board_section(lines)
    assert rows == [[".", ".", "."], ["wP", "wP", "wP"]]


def test_parse_board_section_skips_blank_lines():
    lines = ["Board:", "wK . .", "", "bK . .", "Commands:"]
    rows = parse_board_section(lines)
    assert rows == [["wK", ".", "."], ["bK", ".", "."]]


def test_parse_board_section_no_commands_marker():
    lines = ["Board:", "wK . .", "bK . ."]
    rows = parse_board_section(lines)
    assert rows == [["wK", ".", "."], ["bK", ".", "."]]


def test_parse_commands_section():
    lines = [
        "Board:",
        "wK .",
        ". bK",
        "Commands:",
        "click 50 50",
        "wait 100",
        "print board",
    ]
    commands = parse_commands_section(lines)
    assert commands == ["click 50 50", "wait 100", "print board"]


def test_parse_commands_section_empty():
    lines = ["Board:", "wK .", "Commands:"]
    commands = parse_commands_section(lines)
    assert commands == []


# ==========================================
# validate_board
# ==========================================

def test_valid_board_does_not_raise():
    rows = [["wK", ".", "bK"], [".", ".", "."]]
    validate_board(rows, LEGAL)


def test_empty_board_does_not_raise():
    validate_board([], LEGAL)


def test_row_width_mismatch_raises():
    rows = [["wK", "."], ["bK", ".", "."]]
    with pytest.raises(BoardValidationError) as exc_info:
        validate_board(rows, LEGAL)
    assert exc_info.value.code == ERROR_ROW_WIDTH_MISMATCH


def test_unknown_token_raises():
    rows = [["wK", "zZ"], [".", "."]]
    with pytest.raises(BoardValidationError) as exc_info:
        validate_board(rows, LEGAL)
    assert exc_info.value.code == ERROR_UNKNOWN_TOKEN


def test_width_mismatch_checked_before_later_rows():
    rows = [["wK"], ["wK", "bK"]]
    with pytest.raises(BoardValidationError) as exc_info:
        validate_board(rows, LEGAL)
    assert exc_info.value.code == ERROR_ROW_WIDTH_MISMATCH

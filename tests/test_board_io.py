import io as pyio

from board.board_io import read_input_lines, parse_board_section


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
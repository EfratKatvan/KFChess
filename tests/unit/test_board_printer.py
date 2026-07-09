from kungfu_chess.io.board_parser import build_board
from kungfu_chess.io.board_printer import format_board, print_board


def test_format_board_returns_canonical_lines():
    board = build_board([["wK", ".", "bK"], [".", ".", "."]])
    assert format_board(board) == ["wK . bK", ". . ."]


def test_print_board_calls_print_fn_per_line():
    board = build_board([["wK", "."], [".", "bK"]])
    printed = []
    print_board(board, print_fn=printed.append)
    assert printed == ["wK .", ". bK"]

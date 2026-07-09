from kungfu_chess.model.board import Board
from kungfu_chess.io.board_printer import format_board, print_board


def test_format_board_returns_canonical_lines():
    board = Board.from_rows([["wK", ".", "bK"], [".", ".", "."]])
    assert format_board(board) == ["wK . bK", ". . ."]


def test_print_board_calls_print_fn_per_line():
    board = Board.from_rows([["wK", "."], [".", "bK"]])
    printed = []
    print_board(board, print_fn=printed.append)
    assert printed == ["wK .", ". bK"]

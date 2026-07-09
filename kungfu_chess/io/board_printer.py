from __future__ import annotations
from typing import Callable

from kungfu_chess.model.board import Board


def format_board(board: Board) -> list[str]:
    """מייצר את הייצוג הטקסטואלי הקנוני של הלוח, שורה לכל תא-שורה."""
    return [" ".join(row) for row in board.to_rows()]


def print_board(board: Board, print_fn: Callable[[str], None] = print) -> None:
    for line in format_board(board):
        print_fn(line)

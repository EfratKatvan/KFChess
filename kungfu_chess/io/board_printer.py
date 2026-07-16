from __future__ import annotations
from typing import Callable

from kungfu_chess.model.board import Board
from kungfu_chess.model.position import Position
from kungfu_chess.io.board_parser import piece_to_token, EMPTY_CELL


def format_board(board: Board) -> list[str]:
    lines = []
    for row in range(board.height):
        tokens = []
        for col in range(board.width):
            piece = board.piece_at(Position(row, col))
            tokens.append(piece_to_token(piece) if piece else EMPTY_CELL)
        lines.append(" ".join(tokens))
    return lines


def print_board(board: Board, print_fn: Callable[[str], None] = print) -> None:
    for line in format_board(board):
        print_fn(line)

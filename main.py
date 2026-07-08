# Git repo: https://github.com/EfratKatvan/KFChess.git
import sys

from config.constants import build_legal_tokens
from board.board_io import read_input_lines, parse_board_section
from board.validator import validate_board
from board.model import Board
from board.errors import BoardValidationError


def main() -> None:
    lines = read_input_lines(sys.stdin)
    rows = parse_board_section(lines)

    try:
        validate_board(rows, build_legal_tokens())
    except BoardValidationError as error:
        print(error.code)
        return

    board = Board.from_rows(rows)
    for line in board.to_canonical_lines():
        print(line)


if __name__ == "__main__":
    main()
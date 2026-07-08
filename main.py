# Git repo: https://github.com/EfratKatvan/KFChess.git
from __future__ import annotations
import sys

from config.constants import build_legal_tokens
from board.board_io import read_input_lines, parse_board_section, parse_commands_section
from board.validator import validate_board
from board.model import Board
from board.errors import BoardValidationError
from game.controller import GameController


def main() -> None:
    lines = read_input_lines(sys.stdin)
    rows = parse_board_section(lines)

    try:
        validate_board(rows, build_legal_tokens())
    except BoardValidationError as error:
        print(error.code)
        return

    board = Board.from_rows(rows)
    commands = parse_commands_section(lines)

    # אם לא ניתנו פקודות כלל (או שהרשימה ריקה), מדפיסים את הלוח ההתחלתי בצורה קנונית
    if not commands:
        for line in board.to_canonical_lines():
            print(line)
        return

    # אם יש פקודות, מריצים אותן בעזרת ה-GameController
    controller = GameController(board)
    for cmd in commands:
        controller.execute_command(cmd)


if __name__ == "__main__":
    main()
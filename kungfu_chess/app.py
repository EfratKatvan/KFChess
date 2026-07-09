# Git repo: https://github.com/EfratKatvan/KFChess.git
from __future__ import annotations
import sys

from kungfu_chess.io.board_parser import (
    build_legal_tokens,
    read_input_lines,
    parse_board_section,
    parse_commands_section,
    validate_board,
    BoardValidationError,
)
from kungfu_chess.io.board_printer import print_board
from kungfu_chess.model.board import Board
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.input.controller import Controller
from kungfu_chess.texttests.script_runner import run_commands


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

    if not commands:
        print_board(board)
        return

    rule_engine = RuleEngine(board)
    arbiter = RealTimeArbiter(board)
    engine = GameEngine(board, rule_engine, arbiter)
    mapper = BoardMapper(board)
    controller = Controller(mapper, engine)

    run_commands(commands, controller, engine, board)


if __name__ == "__main__":
    main()

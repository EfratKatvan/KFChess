from __future__ import annotations
from typing import Callable, List

from kungfu_chess.model.board import Board
from kungfu_chess.input.controller import Controller
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.io.board_printer import print_board
from kungfu_chess.texttests.script_parser import parse_line


def run_commands(
    commands: List[str],
    controller: Controller,
    engine: GameEngine,
    board: Board,
    print_fn: Callable[[str], None] = print,
) -> None:
    """מריץ רשימת פקודות טקסט (click / jump / wait / print board) דרך הנתיב הציבורי בלבד."""
    for line in commands:
        command = parse_line(line)
        if command is None:
            continue

        if command.name == "print":
            if command.args[:1] == ["board"]:
                print_board(board, print_fn)
            continue

        if engine.is_game_over():
            continue

        if command.name == "click":
            x, y = int(command.args[0]), int(command.args[1])
            controller.handle_click(x, y)
        elif command.name == "jump":
            x, y = int(command.args[0]), int(command.args[1])
            controller.handle_jump(x, y)
        elif command.name == "wait":
            time_ms = int(command.args[0])
            engine.wait(time_ms)

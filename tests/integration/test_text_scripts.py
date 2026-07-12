import io
import os
import subprocess
import sys

import pytest

from main import main
from kungfu_chess.io.board_parser import (
    read_input_lines,
    parse_board_section,
    parse_commands_section,
    build_board,
)
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.input.controller import Controller
from kungfu_chess.texttests.script_runner import run_commands

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")

# print board הוא מנגנון האסרשן היחיד לטסטי אינטגרציה (סעיף 15) - לכן הפלט
# הצפוי לכל סקריפט מוגדר כאן, לצד הסקריפט עצמו, ולא בתוך קובץ ה-.kfc.
EXPECTED_OUTPUT = {
    "01_board_parsing.kfc": ["wK . bK", ". . ."],
    "02_click_to_move.kfc": [". . wR", ". . ."],
    "03_rook_moves.kfc": [". . .", ". . .", "wR . ."],
    "04_invalid_moves.kfc": ["wR . .", ". . ."],
    "05_capture.kfc": [". . wR", ". . ."],
    "06_game_over.kfc": [". . wR", ". . ."],  # game_over -> המהלך החוזר נדחה, הלוח לא זז
}


def run_lines(lines):
    """מריץ תוכן DSL (Board:/Commands:) דרך הנתיב הציבורי המלא בלבד
    (build_board -> RuleEngine/RealTimeArbiter/GameEngine/Controller ->
    script_runner.run_commands) ומחזיר את שורות ה-print board. אין כאן
    שום קיצור דרך - זה בדיוק מה ש-app.py עושה, בלי תת-תהליך."""
    board = build_board(parse_board_section(lines))
    commands = parse_commands_section(lines)

    rule_engine = RuleEngine(board)
    arbiter = RealTimeArbiter(board)
    engine = GameEngine(board, rule_engine, arbiter)
    mapper = BoardMapper(board)
    controller = Controller(mapper, engine)

    printed = []
    run_commands(commands, controller, engine, board, print_fn=printed.append)
    return printed


def run_script(filename: str):
    path = os.path.join(SCRIPTS_DIR, filename)
    with open(path, encoding="utf-8") as stream:
        lines = read_input_lines(stream)
    return run_lines(lines)


def run_inline(text: str):
    return run_lines(read_input_lines(io.StringIO(text)))


@pytest.mark.parametrize("filename", sorted(EXPECTED_OUTPUT))
def test_kfc_script_produces_expected_board(filename):
    assert run_script(filename) == EXPECTED_OUTPUT[filename]


# ==========================================
# תרחיש קליק->wait->print board קטן לכל סוג כלי (מקצה לקצה, דרך הנתיב
# הציבורי המלא) - Rook כבר מכוסה ע"י 03_rook_moves.kfc למעלה.
# ==========================================

def test_bishop_end_to_end_click_wait_print():
    text = """Board:
wB . .
. . .
. . .
Commands:
click 50 50
click 250 250
wait 2000
print board
"""
    assert run_inline(text) == [". . .", ". . .", ". . wB"]


def test_queen_end_to_end_click_wait_print():
    text = """Board:
wQ . .
. . .
. . .
Commands:
click 50 50
click 250 250
wait 2000
print board
"""
    assert run_inline(text) == [". . .", ". . .", ". . wQ"]


def test_knight_end_to_end_click_wait_print():
    text = """Board:
wN wP .
wP wP .
. . .
Commands:
click 50 50
click 150 250
wait 2000
print board
"""
    assert run_inline(text) == [". wP .", "wP wP .", ". wN ."]


def test_king_end_to_end_click_wait_print():
    text = """Board:
wK . .
. . .
Commands:
click 50 50
click 150 50
wait 1000
print board
"""
    assert run_inline(text) == [". wK .", ". . ."]


def test_pawn_end_to_end_click_wait_print():
    text = """Board:
. . .
. . .
wP . .
. . .
Commands:
click 50 250
click 50 150
wait 1000
print board
"""
    assert run_inline(text) == [". . .", "wP . .", ". . .", ". . ."]


def run_app(stdin_text: str) -> str:
    result = subprocess.run(
        [sys.executable, "main.py"],
        input=stdin_text,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    return result.stdout


def test_valid_board_printed_canonically():
    stdin_text = "Board:\nwK . bK\n. . .\nCommands:\n"
    assert run_app(stdin_text) == "wK . bK\n. . .\n"


def test_row_width_mismatch_prints_error():
    stdin_text = "Board:\nwK .\nbK . .\nCommands:\n"
    assert run_app(stdin_text) == "ERROR ROW_WIDTH_MISMATCH\n"


def test_unknown_token_prints_error():
    stdin_text = "Board:\nwK zZ\n. .\nCommands:\n"
    assert run_app(stdin_text) == "ERROR UNKNOWN_TOKEN\n"


def test_no_commands_marker_reads_to_end():
    stdin_text = "Board:\nwK . .\nbK . .\n"
    assert run_app(stdin_text) == "wK . .\nbK . .\n"


def test_full_flow_click_wait_print_board(monkeypatch, capsys):
    input_data = """Board:
                    wR .
                    . bK
                    Commands:
                    click 50 50
                    click 150 50
                    wait 1000
                    print board
                    """
    monkeypatch.setattr("sys.stdin", io.StringIO(input_data))

    main()

    captured = capsys.readouterr()
    expected_output = ". wR\n. bK\n"
    assert captured.out == expected_output

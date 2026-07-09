import io
import os
import subprocess
import sys

from kungfu_chess.app import main

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_app(stdin_text: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "kungfu_chess.app"],
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

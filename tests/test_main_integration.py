import subprocess
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_PATH = os.path.join(PROJECT_ROOT, "main.py")


def run_main(stdin_text: str) -> str:
    result = subprocess.run(
        [sys.executable, MAIN_PATH],
        input=stdin_text,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    return result.stdout


def test_valid_board_printed_canonically():
    stdin_text = "Board:\nwK . bK\n. . .\nCommands:\n"
    assert run_main(stdin_text) == "wK . bK\n. . .\n"


def test_row_width_mismatch_prints_error():
    stdin_text = "Board:\nwK .\nbK . .\nCommands:\n"
    assert run_main(stdin_text) == "ERROR ROW_WIDTH_MISMATCH\n"


def test_unknown_token_prints_error():
    stdin_text = "Board:\nwK zZ\n. .\nCommands:\n"
    assert run_main(stdin_text) == "ERROR UNKNOWN_TOKEN\n"


def test_no_commands_marker_reads_to_end():
    stdin_text = "Board:\nwK . .\nbK . .\n"
    assert run_main(stdin_text) == "wK . .\nbK . .\n"

import io
from main import main


def test_full_flow_iteration_2(monkeypatch, capsys):
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
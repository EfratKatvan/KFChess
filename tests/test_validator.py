import pytest

from board.validator import validate_board
from board.errors import (
    BoardValidationError,
    ERROR_ROW_WIDTH_MISMATCH,
    ERROR_UNKNOWN_TOKEN,
)
from config.constants import build_legal_tokens

LEGAL = build_legal_tokens()


def test_valid_board_does_not_raise():
    rows = [["wK", ".", "bK"], [".", ".", "."]]
    validate_board(rows, LEGAL)


def test_empty_board_does_not_raise():
    validate_board([], LEGAL)


def test_row_width_mismatch_raises():
    rows = [["wK", "."], ["bK", ".", "."]]
    with pytest.raises(BoardValidationError) as exc_info:
        validate_board(rows, LEGAL)
    assert exc_info.value.code == ERROR_ROW_WIDTH_MISMATCH


def test_unknown_token_raises():
    rows = [["wK", "zZ"], [".", "."]]
    with pytest.raises(BoardValidationError) as exc_info:
        validate_board(rows, LEGAL)
    assert exc_info.value.code == ERROR_UNKNOWN_TOKEN


def test_width_mismatch_checked_before_later_rows():
    rows = [["wK"], ["wK", "bK"]]
    with pytest.raises(BoardValidationError) as exc_info:
        validate_board(rows, LEGAL)
    assert exc_info.value.code == ERROR_ROW_WIDTH_MISMATCH
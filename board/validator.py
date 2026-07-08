from __future__ import annotations
from board.errors import (
    BoardValidationError,
    ERROR_ROW_WIDTH_MISMATCH,
    ERROR_UNKNOWN_TOKEN,
)


def validate_board(rows: list[list[str]], legal_tokens: set[str]) -> None:
    if not rows:
        return

    width = len(rows[0])
    for row in rows:
        if len(row) != width:
            raise BoardValidationError(ERROR_ROW_WIDTH_MISMATCH)
        for cell in row:
            if cell not in legal_tokens:
                raise BoardValidationError(ERROR_UNKNOWN_TOKEN)
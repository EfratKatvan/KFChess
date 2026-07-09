from __future__ import annotations

BOARD_MARKER = "Board:"
COMMANDS_MARKER = "Commands:"
EMPTY_CELL = "."

COLORS = ("w", "b")
PIECE_TYPES = ("K", "Q", "R", "B", "N", "P")


def build_legal_tokens() -> set[str]:
    tokens = {EMPTY_CELL}
    for color in COLORS:
        for piece in PIECE_TYPES:
            tokens.add(f"{color}{piece}")
    return tokens


ERROR_ROW_WIDTH_MISMATCH = "ERROR ROW_WIDTH_MISMATCH"
ERROR_UNKNOWN_TOKEN = "ERROR UNKNOWN_TOKEN"


class BoardValidationError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


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


def read_input_lines(stream) -> list[str]:
    return [line.strip() for line in stream.read().splitlines()]


def parse_board_section(lines: list[str]) -> list[list[str]]:
    start = lines.index(BOARD_MARKER) + 1
    rows: list[list[str]] = []
    i = start
    while i < len(lines) and lines[i] != COMMANDS_MARKER:
        if lines[i]:
            rows.append(lines[i].split())
        i += 1
    return rows


def parse_commands_section(lines: list[str]) -> list[str]:
    """מחזירה את שורות הפקודות שמופיעות אחרי המרקר Commands:"""
    if COMMANDS_MARKER not in lines:
        return []
    start = lines.index(COMMANDS_MARKER) + 1
    return [line for line in lines[start:] if line]

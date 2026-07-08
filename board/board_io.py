from __future__ import annotations
from config.constants import BOARD_MARKER, COMMANDS_MARKER


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
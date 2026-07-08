from __future__ import annotations
"""
Central configuration for board parsing.
Iteration 1: only fixture markers and legal-token generation live here.
"""

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
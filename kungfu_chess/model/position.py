from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Position:
    """A board cell (row, col) - not pixels, not an array index.

    Position intentionally doesn't validate board bounds - that's
    Board's job alone."""

    row: int
    col: int

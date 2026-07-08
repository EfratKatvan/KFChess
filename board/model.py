from __future__ import annotations
class Board:
    def __init__(self, rows: list[list[str]]):
        self._rows = rows

    @classmethod
    def from_rows(cls, rows: list[list[str]]) -> "Board":
        return cls(rows)

    @property
    def height(self) -> int:
        return len(self._rows)

    @property
    def width(self) -> int:
        return len(self._rows[0]) if self._rows else 0

    def to_canonical_lines(self) -> list[str]:
        return [" ".join(row) for row in self._rows]
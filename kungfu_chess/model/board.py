from __future__ import annotations


class Board:
    def __init__(self, rows: list[list[str]]):
        self._rows = rows

    @classmethod
    def from_rows(cls, rows: list[list[str]]) -> "Board":
        # יוצרים עותק נפרד של השורות כדי למנוע שינויים לא רצויים
        return cls([row[:] for row in rows])

    @property
    def height(self) -> int:
        return len(self._rows)

    @property
    def width(self) -> int:
        return len(self._rows[0]) if self._rows else 0

    def to_rows(self) -> list[list[str]]:
        """מחזיר עותק של כל שורות הלוח, בלי לחשוף את הייצוג הפנימי."""
        return [row[:] for row in self._rows]

    def is_inside(self, row: int, col: int) -> bool:
        """בודק אם תא (row, col) נמצא בתוך גבולות הלוח"""
        return 0 <= row < self.height and 0 <= col < self.width

    def get_cell(self, row: int, col: int) -> str:
        """מחזיר את הערך/הכלי שנמצא בתא"""
        return self._rows[row][col]

    def set_cell(self, row: int, col: int, value: str) -> None:
        """מעדכן את הערך בתא"""
        self._rows[row][col] = value

    def move_piece(self, src_row: int, src_col: int, dst_row: int, dst_col: int) -> None:
        """מזיז כלי מתא מקור ותופס/מנקה את תא היעד"""
        piece = self.get_cell(src_row, src_col)
        self.set_cell(src_row, src_col, ".")
        self.set_cell(dst_row, dst_col, piece)

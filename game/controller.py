from __future__ import annotations
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from board.model import Board


def is_path_clear(
    board_rows: list[list[str]], from_pos: Tuple[int, int], to_pos: Tuple[int, int]
) -> bool:
    """
    בודקת אם המסלול בין משבצת המוצא למשבצת היעד פנוי מכלים.
    אינה בודקת את משבצת היעד עצמה (מכיוון ששם מותרת אכילה).
    """
    r1, c1 = from_pos
    r2, c2 = to_pos

    dr = r2 - r1
    dc = c2 - c1

    # חישוב כיוון הצעד (-1, 0, או 1)
    step_r = 0 if dr == 0 else (1 if dr > 0 else -1)
    step_c = 0 if dc == 0 else (1 if dc > 0 else -1)

    curr_r = r1 + step_r
    curr_c = c1 + step_c

    # מתקדמים צעד-צעד עד שמגיעים ליעד (לא כולל היעד)
    while (curr_r, curr_c) != (r2, c2):
        if board_rows[curr_r][curr_c] != ".":
            return False  # יש כלי שחוסם את הדרך
        curr_r += step_r
        curr_c += step_c

    return True


def is_legal_piece_move(
    piece_type: str,
    from_pos: Tuple[int, int],
    to_pos: Tuple[int, int],
    board_rows: Optional[list[list[str]]] = None,
) -> bool:
    """
    בודק חוקיות תנועה כולל חסימות ומסלולים:
    - צורת תנועה לפי הכלי (K, R, B, Q, N)
    - בדיקת מסלול פנוי (עבור R, B, Q)
    """
    r1, c1 = from_pos
    r2, c2 = to_pos

    dr = abs(r2 - r1)
    dc = abs(c2 - c1)

    # ללא תנועה
    if dr == 0 and dc == 0:
        return False

    # 1. בדיקת צורת התנועה הבסיסית
    shape_valid = False
    if piece_type == "K":
        shape_valid = dr <= 1 and dc <= 1
    elif piece_type == "R":
        shape_valid = dr == 0 or dc == 0
    elif piece_type == "B":
        shape_valid = dr == dc
    elif piece_type == "Q":
        shape_valid = dr == 0 or dc == 0 or dr == dc
    elif piece_type == "N":
        shape_valid = (dr == 2 and dc == 1) or (dr == 1 and dc == 2)

    if not shape_valid:
        return False

    # 2. בדיקת מסלול פנוי עבור כלים שנעים בקו ישר/אלכסון (R, B, Q)
    if piece_type in ("R", "B", "Q") and board_rows is not None:
        if not is_path_clear(board_rows, from_pos, to_pos):
            return False

    return True


class GameController:
    def __init__(self, board: Board) -> None:
        self.board = board
        self.selected_pos: Optional[Tuple[int, int]] = None

    def execute_command(self, cmd: str) -> None:
        cmd = cmd.strip()
        if not cmd:
            return

        parts = cmd.split()
        action = parts[0]

        if action == "click":
            if len(parts) == 3:
                x = int(parts[1])
                y = int(parts[2])
                self._handle_click(x, y)
        elif action == "print" and len(parts) >= 2 and parts[1] == "board":
            self._handle_print_board()

    def _handle_click(self, x: int, y: int) -> None:
        col = x // 100
        row = y // 100

        # בדיקה שהלחיצה בתוך גבולות הלוח
        if row < 0 or row >= self.board.height or col < 0 or col >= self.board.width:
            return

        target_token = self.board._rows[row][col]

        # 1. אם עדיין לא נבחר כלי
        if self.selected_pos is None:
            if target_token != ".":
                self.selected_pos = (row, col)
            return

        # 2. אם כבר נבחר כלי בעבר
        sel_row, sel_col = self.selected_pos
        source_token = self.board._rows[sel_row][sel_col]

        # לחיצה שוב על אותה המשבצת
        if (sel_row, sel_col) == (row, col):
            return

        # לחיצה על כלי מאותו הצבע -> העברת הבחירה לכלי החדש
        if target_token != "." and target_token[0] == source_token[0]:
            self.selected_pos = (row, col)
            return

        # 3. בדיקת חוקיות תנועה (צורת כלי + מסלול חופשי)
        piece_type = source_token[1]
        if is_legal_piece_move(
            piece_type, (sel_row, sel_col), (row, col), self.board._rows
        ):
            # ביצוע התנועה / האכילה (כלי יריב מוחלף, משבצת המקור מתרוקנת)
            self.board._rows[row][col] = source_token
            self.board._rows[sel_row][sel_col] = "."
            self.selected_pos = None  # איפוס הבחירה

    def _handle_print_board(self) -> None:
        for line in self.board.to_canonical_lines():
            print(line)
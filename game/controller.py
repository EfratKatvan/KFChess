from __future__ import annotations
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from board.model import Board


def is_legal_piece_move(
    piece_type: str, from_pos: Tuple[int, int], to_pos: Tuple[int, int]
) -> bool:
    """
    בודק אם התנועה מתאימה לצורת התנועה של הכלי:
    K - King (צעד אחד לכל כיוון)
    R - Rook (קו ישר: אופקי או אנכי)
    B - Bishop (אלכסון בלבד)
    Q - Queen (קו ישר או אלכסון)
    N - Knight (תנועת L: 2x1 או 1x2)
    """
    r1, c1 = from_pos
    r2, c2 = to_pos

    dr = abs(r2 - r1)
    dc = abs(c2 - c1)

    # אם לא בוצעה תנועה למיקום שונה
    if dr == 0 and dc == 0:
        return False

    if piece_type == "K":
        return dr <= 1 and dc <= 1
    elif piece_type == "R":
        return dr == 0 or dc == 0
    elif piece_type == "B":
        return dr == dc
    elif piece_type == "Q":
        return dr == 0 or dc == 0 or dr == dc
    elif piece_type == "N":
        return (dr == 2 and dc == 1) or (dr == 1 and dc == 2)

    return False


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
        # המרת קואורדינטות (Pixels / Grid Units) לשורות ועמודות
        col = x // 100
        row = y // 100

        # בדיקה שהלחיצה בתוך גבולות הלוח
        if row < 0 or row >= self.board.height or col < 0 or col >= self.board.width:
            return

        target_token = self.board._rows[row][col]

        # אם עדיין לא נבחר כלי (Selection)
        if self.selected_pos is None:
            if target_token != ".":
                self.selected_pos = (row, col)
            return

        # אם כבר נבחר כלי בעבר
        sel_row, sel_col = self.selected_pos
        source_token = self.board._rows[sel_row][sel_col]

        # אם נלחצה אותה משבצת שוב
        if (sel_row, sel_col) == (row, col):
            return

        # אם נלחץ כלי אחר באותו הצבע - משנים את הבחירה לכלי החדש
        if target_token != "." and target_token[0] == source_token[0]:
            self.selected_pos = (row, col)
            return

        # בדיקת תנועה חוקית לפי צורת הכלי
        piece_type = source_token[1]  # הסוג: K, R, B, Q, N וכד'
        if is_legal_piece_move(piece_type, (sel_row, sel_col), (row, col)):
            # ביצוע התנועה בלוח
            self.board._rows[row][col] = source_token
            self.board._rows[sel_row][sel_col] = "."
            self.selected_pos = None  # איפוס הבחירה לאחר מהלך חוקי
        else:
            # אם המהלך אינו חוקי לפי צורת הכלי - התעלמות מהמהלך
            pass

    def _handle_print_board(self) -> None:
        for line in self.board.to_canonical_lines():
            print(line)
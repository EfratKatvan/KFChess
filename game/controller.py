from __future__ import annotations
from board.model import Board
from config.constants import CELL_SIZE, EMPTY_CELL


class GameController:
    def __init__(self, board: Board):
        self.board = board
        self.selected_pos: tuple[int, int] | None = None  # (row, col) של הכלי הנבחר
        self.clock_ms: int = 0  # שעון המשחק במילי-שניות

    def handle_click(self, x: int, y: int) -> None:
        # 1. המרה מקואורדינטות פיקסל לתאי לוח
        col = x // CELL_SIZE
        row = y // CELL_SIZE

        # 2. אם הלחיצה מחוץ לגבולות הלוח - התעלמות
        if not self.board.is_inside(row, col):
            return

        clicked_cell = self.board.get_cell(row, col)

        # 3. אם כרגע אין כלי נבחר
        if self.selected_pos is None:
            if clicked_cell != EMPTY_CELL:
                # לחיצה על כלי מסמנת אותו
                self.selected_pos = (row, col)
            # לחיצה על תא ריק כשאין בחירה -> התעלמות
            return

        # 4. אם כבר יש כלי נבחר
        src_row, src_col = self.selected_pos

        # אם לחצנו שוב על אותו תא בדיוק
        if (src_row, src_col) == (row, col):
            return

        # אם לחצנו על כלי אחר (באיטרציה 2: מחליף את הבחירה לכלי החדש)
        if clicked_cell != EMPTY_CELL:
            self.selected_pos = (row, col)
        else:
            # לחצנו על תא ריק -> מזיזים את הכלי הנבחר לשם ומאפסים את הבחירה
            self.board.move_piece(src_row, src_col, row, col)
            self.selected_pos = None

    def handle_wait(self, ms: int) -> None:
        # מקדם את שעון המשחק (באיטרציות הבאות ישפיע על מעוף הכלים וזמני צינון)
        self.clock_ms += ms

    def execute_command(self, cmd_line: str) -> None:
        parts = cmd_line.split()
        if not parts:
            return

        cmd = parts[0]

        if cmd == "click":
            x, y = int(parts[1]), int(parts[2])
            self.handle_click(x, y)

        elif cmd == "wait":
            ms = int(parts[1])
            self.handle_wait(ms)

        elif cmd == "print" and len(parts) > 1 and parts[1] == "board":
            for line in self.board.to_canonical_lines():
                print(line)
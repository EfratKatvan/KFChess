from __future__ import annotations
from typing import TYPE_CHECKING, Optional, Tuple, List, Dict, Any

if TYPE_CHECKING:
    from board.model import Board


def is_path_clear(
    board_rows: list[list[str]], from_pos: Tuple[int, int], to_pos: Tuple[int, int]
) -> bool:
    r1, c1 = from_pos
    r2, c2 = to_pos

    dr = r2 - r1
    dc = c2 - c1

    step_r = 0 if dr == 0 else (1 if dr > 0 else -1)
    step_c = 0 if dc == 0 else (1 if dc > 0 else -1)

    curr_r = r1 + step_r
    curr_c = c1 + step_c

    while (curr_r, curr_c) != (r2, c2):
        if board_rows[curr_r][curr_c] != ".":
            return False
        curr_r += step_r
        curr_c += step_c

    return True


def get_route_cells(sr: int, sc: int, tr: int, tc: int) -> List[Tuple[int, int]]:
    """מחזירה את כל התאים שהמסלול עובר דרכם (כולל מקור ויעד)."""
    dr = tr - sr
    dc = tc - sc
    steps = max(abs(dr), abs(dc))
    if steps == 0:
        return [(sr, sc)]

    step_r = dr // steps if dr != 0 else 0
    step_c = dc // steps if dc != 0 else 0

    return [(sr + i * step_r, sc + i * step_c) for i in range(steps + 1)]


def has_common_route(
    sr1: int, sc1: int, tr1: int, tc1: int,
    sr2: int, sc2: int, tr2: int, tc2: int
) -> bool:
    """בודק חפיפת מסלול (Common Route) בין שתי תנועות."""
    cols1 = range(min(sc1, tc1), max(sc1, tc1) + 1)
    cols2 = range(min(sc2, tc2), max(sc2, tc2) + 1)
    col_overlap = bool(set(cols1) & set(cols2))

    rows1 = range(min(sr1, tr1), max(sr1, tr1) + 1)
    rows2 = range(min(sr2, tr2), max(sr2, tr2) + 1)
    row_overlap = bool(set(rows1) & set(rows2))

    if sc1 != tc1 and sc2 != tc2 and col_overlap:
        return True

    if sr1 != tr1 and sr2 != tr2 and row_overlap:
        return True

    route1 = set(get_route_cells(sr1, sc1, tr1, tc1))
    route2 = set(get_route_cells(sr2, sc2, tr2, tc2))
    return bool(route1 & route2)


def is_legal_pawn_move(
    color: str,
    from_pos: Tuple[int, int],
    to_pos: Tuple[int, int],
    target_token: str,
) -> bool:
    r1, c1 = from_pos
    r2, c2 = to_pos

    dr = r2 - r1
    dc = abs(c2 - c1)

    expected_dr = -1 if color == "w" else 1

    if dr != expected_dr:
        return False

    if dc == 0:
        return target_token == "."

    if dc == 1:
        return target_token != "." and target_token[0] != color

    return False


def is_legal_piece_move(
    source_token: str,
    from_pos: Tuple[int, int],
    to_pos: Tuple[int, int],
    board_rows: Optional[list[list[str]]] = None,
    target_token: str = ".",
) -> bool:
    r1, c1 = from_pos
    r2, c2 = to_pos

    dr = abs(r2 - r1)
    dc = abs(c2 - c1)

    if dr == 0 and dc == 0:
        return False

    color = source_token[0]
    piece_type = source_token[1]

    if piece_type == "P":
        return is_legal_pawn_move(color, from_pos, to_pos, target_token)

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

    if piece_type in ("R", "B", "Q") and board_rows is not None:
        if not is_path_clear(board_rows, from_pos, to_pos):
            return False

    return True


class GameController:
    def __init__(self, board: Board) -> None:
        self.board = board
        self.selected_pos: Optional[Tuple[int, int]] = None
        # [ (piece, sr, sc, tr, tc, remaining_time) ]
        self.moving_pieces: List[Tuple[str, int, int, int, int, int]] = []

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
        elif action == "wait" and len(parts) >= 2:
            wait_time = int(parts[1])
            self._handle_wait(wait_time)
        elif action == "print" and len(parts) >= 2 and parts[1] == "board":
            self._handle_print_board()

    def _handle_click(self, x: int, y: int) -> None:
        col = x // 100
        row = y // 100

        if row < 0 or row >= self.board.height or col < 0 or col >= self.board.width:
            return

        moving_sources = {(sr, sc) for (_, sr, sc, _, _, _) in self.moving_pieces}

        # מניעת בחירה או מתן פקודה לכלי שכרגע נמצא בתנועה
        if (row, col) in moving_sources:
            return

        target_token = self.board._rows[row][col]

        if self.selected_pos is None:
            if target_token != ".":
                self.selected_pos = (row, col)
            return

        sel_row, sel_col = self.selected_pos
        source_token = self.board._rows[sel_row][sel_col]

        if (sel_row, sel_col) == (row, col):
            return

        # שינוי בחירה לכלי אחר מאותו צבע
        if target_token != "." and target_token[0] == source_token[0]:
            self.selected_pos = (row, col)
            return

        # --- איטרציה 8: בדיקות נחיתה וקונפליקטים מתקדמות ---
        
        # 1. בדיקה אם כלי ידידותי זז כרגע ומתוכנן לנחות בתא היעד (row, col)
        for active_piece, msr, msc, mtr, mtc, _ in self.moving_pieces:
            if active_piece[0] == source_token[0]:  # אותו צבע (ידידותי)
                if (mtr, mtc) == (row, col):
                    # התנגשות נחיתה עם כלי ידידותי - התנועה מבוטלת
                    self.selected_pos = None
                    return

        # 2. בדיקת חוקיות התנועה הבסיסית
        if is_legal_piece_move(
            source_token,
            (sel_row, sel_col),
            (row, col),
            self.board._rows,
            target_token,
        ):
            # 3. בדיקת חפיפת מסלולים מול כלים בתנועה בצבע הופכי
            for active_piece, msr, msc, mtr, mtc, _ in self.moving_pieces:
                if active_piece[0] != source_token[0]:  # צבע הופכי
                    if has_common_route(
                        sel_row, sel_col, row, col,
                        msr, msc, mtr, mtc
                    ):
                        self.selected_pos = None
                        return

            distance = max(abs(row - sel_row), abs(col - sel_col))
            travel_time = distance * 1000

            self.moving_pieces.append(
                (source_token, sel_row, sel_col, row, col, travel_time)
            )
            self.selected_pos = None

    def _handle_wait(self, time_ms: int) -> None:
        if not self.moving_pieces:
            return

        new_moving = []
        for piece, sr, sc, tr, tc, remaining in self.moving_pieces:
            remaining -= time_ms
            if remaining <= 0:
                # הגיע ליעד
                self.board._rows[tr][tc] = piece
                if self.board._rows[sr][sc] == piece:
                    self.board._rows[sr][sc] = "."
            else:
                new_moving.append((piece, sr, sc, tr, tc, remaining))

        self.moving_pieces = new_moving

    def _handle_print_board(self) -> None:
        for line in self.board.to_canonical_lines():
            print(line)
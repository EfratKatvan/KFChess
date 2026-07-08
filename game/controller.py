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
        # מבנה לניהול תנועות: [ (piece, sr, sc, tr, tc, remaining_time) ]
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

        # בדיקה אם משבצת במקור כבר נמצאת בתנועה
        moving_sources = {(sr, sc) for (_, sr, sc, _, _, _) in self.moving_pieces}

        if self.selected_pos is None and (row, col) in moving_sources:
            return

        if self.selected_pos is not None and self.selected_pos in moving_sources:
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

        if target_token != "." and target_token[0] == source_token[0]:
            self.selected_pos = (row, col)
            return

        if is_legal_piece_move(
            source_token,
            (sel_row, sel_col),
            (row, col),
            self.board._rows,
            target_token,
        ):
            # חישוב זמן התנועה (Chebyshev Distance * 1000ms)
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
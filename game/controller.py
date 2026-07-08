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
    board_rows: list[list[str]],
    target_token: str,
) -> bool:
    r1, c1 = from_pos
    r2, c2 = to_pos
    board_height = len(board_rows)

    if color == "w":
        direction = -1
        start_row = board_height - 2 if board_height == 8 else board_height - 1
    else:
        direction = 1
        start_row = 1 if board_height == 8 else 0

    if c1 == c2:
        if r2 - r1 == direction and target_token == ".":
            return True
        if r1 == start_row and r2 - r1 == 2 * direction:
            mid_r = r1 + direction
            if board_rows[mid_r][c1] == "." and target_token == ".":
                return True

    if abs(c2 - c1) == 1 and r2 - r1 == direction:
        if target_token != "." and target_token[0] != color:
            return True

    return False


def is_legal_piece_move(
    piece: str,
    from_pos: Tuple[int, int],
    to_pos: Tuple[int, int],
    board_rows: Optional[list[list[str]]] = None,
    target_token: str = ".",
) -> bool:
    if piece == ".":
        return False

    color = piece[0]
    p_type = piece[1]

    r1, c1 = from_pos
    r2, c2 = to_pos

    if r1 == r2 and c1 == c2:
        return False

    dr = abs(r2 - r1)
    dc = abs(c2 - c1)

    if target_token != "." and target_token[0] == color:
        return False

    if p_type == "K":
        return dr <= 1 and dc <= 1

    if p_type == "R":
        if r1 != r2 and c1 != c2:
            return False
        if board_rows is not None and not is_path_clear(board_rows, from_pos, to_pos):
            return False
        return True

    if p_type == "B":
        if dr != dc:
            return False
        if board_rows is not None and not is_path_clear(board_rows, from_pos, to_pos):
            return False
        return True

    if p_type == "Q":
        is_straight = (r1 == r2) or (c1 == c2)
        is_diagonal = dr == dc
        if not (is_straight or is_diagonal):
            return False
        if board_rows is not None and not is_path_clear(board_rows, from_pos, to_pos):
            return False
        return True

    if p_type == "N":
        return (dr == 1 and dc == 2) or (dr == 2 and dc == 1)

    if p_type == "P":
        if board_rows is None:
            return False
        return is_legal_pawn_move(color, from_pos, to_pos, board_rows, target_token)

    return False


class GameController:
    def __init__(self, board: Board) -> None:
        self.board = board
        self.selected_pos: Optional[Tuple[int, int]] = None
        self.moving_pieces: List[Tuple[str, int, int, int, int, int]] = []
        self.jumping_pieces: List[Tuple[int, int, int]] = []  # (row, col, remaining_time)
        self.game_over: bool = False

    def execute_command(self, cmd_line: str) -> None:
        parts = cmd_line.strip().split()
        if not parts:
            return

        cmd_type = parts[0]

        if cmd_type == "print":
            if len(parts) > 1 and parts[1] == "board":
                self._handle_print_board()
            return

        if self.game_over:
            return

        if cmd_type == "click":
            x, y = int(parts[1]), int(parts[2])
            self._handle_click(x, y)

        elif cmd_type == "jump":
            x, y = int(parts[1]), int(parts[2])
            self._handle_jump(x, y)

        elif cmd_type == "wait":
            time_ms = int(parts[1])
            self._handle_wait(time_ms)

    def _handle_jump(self, x: int, y: int) -> None:
        if self.game_over:
            return

        col = x // 100
        row = y // 100

        if not (0 <= row < self.board.height and 0 <= col < self.board.width):
            return

        piece = self.board._rows[row][col]
        if piece == ".":
            return

        for _, sr, sc, tr, tc, _ in self.moving_pieces:
            if (sr, sc) == (row, col) or (tr, tc) == (row, col):
                return

        for jr, jc, rem in self.jumping_pieces:
            if (jr, jc) == (row, col) and rem > 0:
                return

        self.jumping_pieces.append((row, col, 1000))

    def _handle_click(self, x: int, y: int) -> None:
        if self.game_over:
            return

        col = x // 100
        row = y // 100

        if not (0 <= row < self.board.height and 0 <= col < self.board.width):
            return

        if self.selected_pos is None:
            if self.board._rows[row][col] != ".":
                # בדיקה שהכלי שנבחר אינו נמצא כרגע בתנועה פעילה
                for _, sr, sc, tr, tc, _ in self.moving_pieces:
                    if (sr, sc) == (row, col) or (tr, tc) == (row, col):
                        return
                self.selected_pos = (row, col)
        else:
            sel_row, sel_col = self.selected_pos

            if (sel_row, sel_col) == (row, col):
                return

            source_token = self.board._rows[sel_row][sel_col]
            target_token = self.board._rows[row][col]

            if target_token != "." and target_token[0] == source_token[0]:
                # שינוי בחירה לכלי של אותו שחקן (בתנאי שגם הוא לא בתנועה)
                for _, sr, sc, tr, tc, _ in self.moving_pieces:
                    if (sr, sc) == (row, col) or (tr, tc) == (row, col):
                        return
                self.selected_pos = (row, col)
                return

            if not is_legal_piece_move(
                source_token,
                (sel_row, sel_col),
                (row, col),
                self.board._rows,
                target_token,
            ):
                return

            for _, _, _, tr, tc, _ in self.moving_pieces:
                if (tr, tc) == (row, col):
                    self.selected_pos = None
                    return

            distance = max(abs(row - sel_row), abs(col - sel_col))
            travel_time = distance * 1000

            self.moving_pieces.append(
                (source_token, sel_row, sel_col, row, col, travel_time)
            )
            self.selected_pos = None

    def _handle_wait(self, time_ms: int) -> None:
        if self.game_over:
            return

        # 1. עדכון תנועות כלים
        new_moving = []
        for piece, sr, sc, tr, tc, remaining in self.moving_pieces:
            remaining -= time_ms
            if remaining <= 0:
                original_piece = piece

                is_target_airborne = any(
                    jr == tr and jc == tc and j_rem > 0
                    for jr, jc, j_rem in self.jumping_pieces
                )

                if is_target_airborne:
                    if self.board._rows[sr][sc] == original_piece:
                        self.board._rows[sr][sc] = "."

                    if piece[1] == "K":
                        self.game_over = True
                        self.moving_pieces = []
                        return
                else:
                    captured_token = self.board._rows[tr][tc]

                    # הכתרת חייל
                    if piece == "wP" and tr == 0:
                        piece = "wQ"
                    elif piece == "bP" and tr == self.board.height - 1:
                        piece = "bQ"

                    # פינוי תא המקור לפי original_piece
                    if self.board._rows[sr][sc] == original_piece:
                        self.board._rows[sr][sc] = "."

                    # הנחה בתא היעד
                    self.board._rows[tr][tc] = piece

                    if captured_token != "." and captured_token[1] == "K":
                        self.game_over = True
                        self.moving_pieces = []
                        return
            else:
                new_moving.append((piece, sr, sc, tr, tc, remaining))

        self.moving_pieces = new_moving

        # 2. עדכון קפיצות
        new_jumping = []
        for jr, jc, remaining in self.jumping_pieces:
            remaining -= time_ms
            if remaining > 0:
                new_jumping.append((jr, jc, remaining))
        self.jumping_pieces = new_jumping

    def _handle_print_board(self) -> None:
        for line in self.board.to_canonical_lines():
            print(line)
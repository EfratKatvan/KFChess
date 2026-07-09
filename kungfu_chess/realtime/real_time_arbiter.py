from __future__ import annotations
from typing import List, Tuple

from kungfu_chess.model.board import Board
from kungfu_chess.realtime.motion import Motion, Jump

MS_PER_CELL = 1000
JUMP_DURATION_MS = 1000


class RealTimeArbiter:
    """מנהל את התנועות והקפיצות הפעילות, ומקדם אותן עם חלוף הזמן.

    לוגיקת ההגעה, הלכידה וזיהוי לכידת-מלך זהה 1:1 להתנהגות שהייתה קודם
    ב-GameController._handle_wait, כולל העצירה המיידית של כל שאר העיבוד
    (ודילוג על עדכון הקפיצות) ברגע שנלכד מלך.
    """

    def __init__(self, board: Board) -> None:
        self._board = board
        self._motions: List[Motion] = []
        self._jumps: List[Jump] = []

    @property
    def motions(self) -> List[Motion]:
        return list(self._motions)

    @property
    def jumps(self) -> List[Jump]:
        return list(self._jumps)

    def is_cell_busy(self, row: int, col: int) -> bool:
        """True אם התא הוא מקור או יעד של תנועה פעילה (קפיצות אינן נחשבות תפוסות)."""
        return any(
            (m.from_row, m.from_col) == (row, col) or (m.to_row, m.to_col) == (row, col)
            for m in self._motions
        )

    def is_destination_reserved(self, row: int, col: int) -> bool:
        return any((m.to_row, m.to_col) == (row, col) for m in self._motions)

    def is_cell_airborne(self, row: int, col: int) -> bool:
        return any(j.row == row and j.col == col and j.remaining_ms > 0 for j in self._jumps)

    def start_motion(self, piece_token: str, from_pos: Tuple[int, int], to_pos: Tuple[int, int]) -> None:
        from_row, from_col = from_pos
        to_row, to_col = to_pos
        distance = max(abs(to_row - from_row), abs(to_col - from_col))
        travel_time = distance * MS_PER_CELL
        self._motions.append(Motion(piece_token, from_row, from_col, to_row, to_col, travel_time))

    def start_jump(self, row: int, col: int) -> None:
        self._jumps.append(Jump(row, col, JUMP_DURATION_MS))

    def advance(self, time_ms: int) -> bool:
        """מקדם את הזמן ב-time_ms. מחזיר True אם מלך נלכד בסיבוב הזה."""
        new_motions: List[Motion] = []
        for motion in self._motions:
            remaining = motion.remaining_ms - time_ms
            if remaining > 0:
                new_motions.append(
                    Motion(
                        motion.piece_token,
                        motion.from_row,
                        motion.from_col,
                        motion.to_row,
                        motion.to_col,
                        remaining,
                    )
                )
                continue

            if self._resolve_arrival(motion):
                self._motions = []
                return True

        self._motions = new_motions
        self._advance_jumps(time_ms)
        return False

    def _resolve_arrival(self, motion: Motion) -> bool:
        """מיישם הגעה של כלי ליעדו. מחזיר True אם מלך נלכד (כולל לכידת-אוויר)."""
        piece = motion.piece_token
        sr, sc, tr, tc = motion.from_row, motion.from_col, motion.to_row, motion.to_col
        original_piece = piece

        if self.is_cell_airborne(tr, tc):
            if self._board.get_cell(sr, sc) == original_piece:
                self._board.set_cell(sr, sc, ".")
            return piece[1] == "K"

        captured_token = self._board.get_cell(tr, tc)

        if piece == "wP" and tr == 0:
            piece = "wQ"
        elif piece == "bP" and tr == self._board.height - 1:
            piece = "bQ"

        if self._board.get_cell(sr, sc) == original_piece:
            self._board.set_cell(sr, sc, ".")
        self._board.set_cell(tr, tc, piece)

        return captured_token != "." and captured_token[1] == "K"

    def _advance_jumps(self, time_ms: int) -> None:
        new_jumps: List[Jump] = []
        for jump in self._jumps:
            remaining = jump.remaining_ms - time_ms
            if remaining > 0:
                new_jumps.append(Jump(jump.row, jump.col, remaining))
        self._jumps = new_jumps

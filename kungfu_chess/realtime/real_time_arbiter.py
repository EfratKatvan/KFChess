from __future__ import annotations
from typing import List

from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import Piece, WHITE, BLACK, KING, QUEEN, PAWN, IDLE, MOVING, CAPTURED
from kungfu_chess.model.position import Position
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

    def is_cell_busy(self, position: Position) -> bool:
        """True אם התא הוא מקור או יעד של תנועה פעילה (קפיצות אינן נחשבות תפוסות)."""
        return any(m.piece.cell == position or m.to_pos == position for m in self._motions)

    def is_destination_reserved(self, position: Position) -> bool:
        return any(m.to_pos == position for m in self._motions)

    def is_cell_airborne(self, position: Position) -> bool:
        return any(j.position == position and j.remaining_ms > 0 for j in self._jumps)

    def start_motion(self, piece: Piece, to_pos: Position) -> None:
        from_pos = piece.cell
        distance = max(abs(to_pos.row - from_pos.row), abs(to_pos.col - from_pos.col))
        travel_time = distance * MS_PER_CELL
        piece.state = MOVING
        self._motions.append(Motion(piece, to_pos, travel_time))

    def start_jump(self, position: Position) -> None:
        self._jumps.append(Jump(position, JUMP_DURATION_MS))

    def advance_time(self, time_ms: int) -> bool:
        """מקדם את הזמן ב-time_ms. מחזיר True אם מלך נלכד בסיבוב הזה."""
        new_motions: List[Motion] = []
        for motion in self._motions:
            remaining = motion.remaining_ms - time_ms
            if remaining > 0:
                new_motions.append(Motion(motion.piece, motion.to_pos, remaining))
                continue

            if self._resolve_arrival(motion):
                self._motions = []
                return True

        self._motions = new_motions
        self._advance_jumps(time_ms)
        return False

    def _resolve_arrival(self, motion: Motion) -> bool:
        """מיישם הגעה של כלי ליעדו. מחזיר True אם מלך נלכד (כולל לכידת-אוויר)."""
        piece = motion.piece

        if piece.state == CAPTURED:
            # הכלי כבר נלכד במקום אחר (למשל: כלי אויב תקף בהצלחה את תא-המקור
            # שלו בזמן שהוא עדיין "ריחף" משם - is_destination_reserved לא
            # מגן על זה, כי הוא בודק רק יעדים של תנועות אחרות, לא מקורות).
            # התנועה שלו מתבטלת - אין מה להנחית כלי שכבר לא קיים.
            return False

        from_pos = piece.cell
        to_pos = motion.to_pos

        if self.is_cell_airborne(to_pos):
            # הכלי הנע "נבלע" באוויר - הכלי שקפץ נשאר במקומו
            if self._board.piece_at(from_pos) is piece:
                self._board.remove_piece(piece)
            return piece.kind == KING

        captured = self._board.piece_at(to_pos)

        if piece.kind == PAWN and piece.color == WHITE and to_pos.row == 0:
            piece.kind = QUEEN
        elif piece.kind == PAWN and piece.color == BLACK and to_pos.row == self._board.height - 1:
            piece.kind = QUEEN

        # מפנים את תא המקור רק אם הכלי עדיין באמת שם (יכול היה כבר להילכד
        # שם ע"י מהלך אחר שהסתיים באותו tick - ר' realtime/motion.py)
        if self._board.piece_at(from_pos) is piece:
            self._board.remove_piece(piece)

        if captured is not None:
            self._board.remove_piece(captured)
            captured.state = CAPTURED

        piece.cell = to_pos
        piece.state = IDLE
        self._board.add_piece(piece)

        return captured is not None and captured.kind == KING

    def _advance_jumps(self, time_ms: int) -> None:
        new_jumps: List[Jump] = []
        for jump in self._jumps:
            remaining = jump.remaining_ms - time_ms
            if remaining > 0:
                new_jumps.append(Jump(jump.position, remaining))
        self._jumps = new_jumps

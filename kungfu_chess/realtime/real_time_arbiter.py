from __future__ import annotations
from typing import List, Optional

from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import Piece, IDLE, MOVING, CAPTURED
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.motion import (
    Jump,
    Motion,
    Trajectory,
    is_straight_line,
    motion_duration_ms,
    trajectories_collide,
    truncated_before_collision,
)
from kungfu_chess.rules.rule_engine import (
    KingCaptureWinCondition,
    LastRankPromotion,
    PromotionRule,
    WinCondition,
)

JUMP_DURATION_MS = 1000


def _active_trajectory(motion: Motion) -> Optional[Trajectory]:
    """בונה את ה-Trajectory הנוכחי של תנועה פעילה - None אם היא לא ישרה
    (קפיצת-L של סוס, שאין לה מסלול רציף להתנגש עליו)."""
    source = motion.piece.cell
    if not is_straight_line(source, motion.to_pos):
        return None
    duration = motion_duration_ms(source, motion.to_pos)
    elapsed = duration - motion.remaining_ms
    return Trajectory(source, motion.to_pos, duration, start_offset_ms=-elapsed)


class RealTimeArbiter:
    """מנהל את התנועות והקפיצות הפעילות, ומקדם אותן עם חלוף הזמן.

    לוגיקת ההגעה, הלכידה וזיהוי לכידת-מלך זהה 1:1 להתנהגות שהייתה קודם
    ב-GameController._handle_wait, כולל העצירה המיידית של כל שאר העיבוד
    (ודילוג על עדכון הקפיצות) ברגע שנלכד מלך. מה מסיים משחק (WinCondition)
    ומה קורה בהגעה ליעד (PromotionRule) ניתנים להחלפה מבחוץ.
    """

    def __init__(
        self,
        board: Board,
        win_condition: Optional[WinCondition] = None,
        promotion_rule: Optional[PromotionRule] = None,
    ) -> None:
        self._board = board
        self._motions: List[Motion] = []
        self._jumps: List[Jump] = []
        self._win_condition = win_condition if win_condition is not None else KingCaptureWinCondition()
        self._promotion_rule = promotion_rule if promotion_rule is not None else LastRankPromotion()

    @property
    def motions(self) -> List[Motion]:
        return list(self._motions)

    @property
    def jumps(self) -> List[Jump]:
        return list(self._jumps)

    #אם התא הוא מקור או יעד של תנועה פעילה (קפיצות אינן נחשבות תפוסות) - True
    def is_cell_busy(self, position: Position) -> bool:
        """True אם התא הוא מקור או יעד של תנועה פעילה (קפיצות אינן נחשבות תפוסות)."""
        return any(m.piece.cell == position or m.to_pos == position for m in self._motions)

    #אם התא הוא יעד של תנועה פעילה של כלי מאותו צבע - True (כלים מנוגדי-צבע
    #כן יכולים להתחרות על אותו יעד - ר' advance_time; מי שמגיע מאוחר יותר אוכל את מי שהגיע קודם)
    def is_destination_reserved(self, color: str, position: Position) -> bool:
        return any(m.to_pos == position and m.piece.color == color for m in self._motions)

    #אם התא הוא יעד של קפיצה פעילה (קפיצות אינן נחשבות תפוסות) - True
    def is_cell_airborne(self, position: Position) -> bool:
        return any(j.position == position and j.remaining_ms > 0 for j in self._jumps)

    #בדיקה האם בטווח תנועה  של מסלול יש מפגש עם כלי בצבע מנוגד, כך ששני הכלים יהיו באותו מקום באותו זמן (מודל רציף בזמן - ר' realtime/motion.py).
    def has_route_conflict(self, color: str, from_pos: Position, to_pos: Position) -> bool:
        """True אם כלי בצבע מנוגד כבר בתנועה כרגע, ושני הכלים יהיו באותה
        נקודה בדיוק באותו רגע (מודל רציף בזמן - ר' realtime/motion.py),
        לא רק אם המסלולים חוצים את אותו תא. כלים באותו צבע לא נחסמים
        זה מזה. תנועות לא-ישרות (קפיצת סוס) פטורות - אין להן מסלול רציף."""
        if not is_straight_line(from_pos, to_pos):
            return False

        requested = Trajectory(from_pos, to_pos, motion_duration_ms(from_pos, to_pos))

        for motion in self._motions:
            if motion.piece.color == color:
                continue

            active = _active_trajectory(motion)
            if active is None:
                continue

            #בדיקה אם שתי הכלים יפגשו באותו תע בו זמנית
            if trajectories_collide(requested, active):
                return True

        return False

    def truncated_destination(self, color: str, from_pos: Position, to_pos: Position) -> Optional[Position]:
        """אם המהלך המבוקש היה מתנגש (באותה נקודה ובאותו רגע) עם תנועה
        פעילה של כלי מאותו צבע, מחזירה יעד מקוצר - תא אחד לפני נקודת
        ההתנגשות לאורך אותו כיוון (הכלי "נתקע" שם במקום להמשיך). אם כמה
        התנגשויות אפשריות, בוחרת את הקרובה ביותר למקור. אם ההתנגשות
        קורית כבר בצעד הראשון, מחזירה None (אין יעד חוקי בכיוון הזה).
        אחרת מחזירה את היעד המקורי ללא שינוי."""
        if not is_straight_line(from_pos, to_pos):
            return to_pos

        requested = Trajectory(from_pos, to_pos, motion_duration_ms(from_pos, to_pos))

        cutoffs = []
        for motion in self._motions:
            if motion.piece.color != color:
                continue

            active = _active_trajectory(motion)
            if active is None:
                continue

            cutoff = truncated_before_collision(requested, active)
            if cutoff is not None:
                cutoffs.append(cutoff)

        if not cutoffs:
            return to_pos

        closest = min(cutoffs, key=lambda c: max(abs(c.row - from_pos.row), abs(c.col - from_pos.col)))
        return None if closest == from_pos else closest

    def start_motion(self, piece: Piece, to_pos: Position) -> None:
        from_pos = piece.cell
        travel_time = motion_duration_ms(from_pos, to_pos)
        piece.state = MOVING
        self._motions.append(Motion(piece, to_pos, travel_time))

    def start_jump(self, position: Position) -> None:
        self._jumps.append(Jump(position, JUMP_DURATION_MS))

    def advance_time(self, time_ms: int) -> bool:
        """מקדם את הזמן ב-time_ms. מחזיר True אם מלך נלכד בסיבוב הזה.
        מעבד תנועות שמסתיימות באותו tick לפי סדר הגעה כרונולוגי (מי
        שהיה לו פחות remaining_ms מגיע קודם) - כדי שאם שני כלים מגיעים
        לאותו יעד באותו tick, זה שממתין קודם כבר יושב שם כשהשני מגיע
        (ואז נלכד באופן טבעי דרך לכידה רגילה, לא לוגיקה נפרדת)."""
        new_motions: List[Motion] = []
        for motion in sorted(self._motions, key=lambda m: m.remaining_ms):
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

        #אם היעד באויר -היעד אוכל אותו
        if self.is_cell_airborne(to_pos):
            # הכלי הנע "נבלע" באוויר - הכלי שקפץ נשאר במקומו
            if self._board.piece_at(from_pos) is piece:
                self._board.remove_piece(piece)
            return self._win_condition.is_game_over(piece)

        captured = self._board.piece_at(to_pos)

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
        self._promotion_rule.promote(piece, self._board.height)

        return self._win_condition.is_game_over(captured)

    def _advance_jumps(self, time_ms: int) -> None:
        new_jumps: List[Jump] = []
        for jump in self._jumps:
            remaining = jump.remaining_ms - time_ms
            if remaining > 0:
                new_jumps.append(Jump(jump.position, remaining))
        self._jumps = new_jumps

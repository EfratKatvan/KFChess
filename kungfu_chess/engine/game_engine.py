from __future__ import annotations
from dataclasses import dataclass

from kungfu_chess.model.board import Board
from kungfu_chess.model.game_state import GameState
from kungfu_chess.model.game_snapshot import GameSnapshot
from kungfu_chess.model.position import Position
from kungfu_chess.rules.rule_engine import RuleEngine, REASON_OK
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter

REASON_GAME_OVER = "game_over"
REASON_MOTION_IN_PROGRESS = "motion_in_progress"
REASON_DESTINATION_RESERVED = "destination_reserved"
REASON_ROUTE_CONFLICT = "route_conflict"
REASON_BLOCKED_BY_FRIENDLY_MOTION = "blocked_by_friendly_motion"
REASON_COOLING_DOWN = "cooling_down"


@dataclass
class MoveResult:
    is_accepted: bool
    reason: str


class GameEngine:
    """שכבת התיאום (Application Service): הגבול הציבורי שדרכו Controller
    ו-TextTestRunner מבקשים פעולות. מחזיקה את GameState (כולל game_over),
    מאצילה ולידציה טהורה ל-RuleEngine, ומפעילה תנועות/זמן דרך
    RealTimeArbiter. לא מכירה פיקסלים, ציור, פרסור טקסט, או לוגיקת-כלי."""

    def __init__(self, board: Board, rule_engine: RuleEngine, arbiter: RealTimeArbiter) -> None:
        self._state = GameState(board=board)
        self._rules = rule_engine
        self._arbiter = arbiter

    def is_game_over(self) -> bool:
        return self._state.game_over

    def is_busy(self, position: Position) -> bool:
        return self._arbiter.is_cell_busy(position)

    def is_cooling_down(self, position: Position) -> bool:
        return self._arbiter.is_cell_cooling_down(position)

    def has_piece(self, position: Position) -> bool:
        return self._state.board.piece_at(position) is not None

    def is_same_color(self, pos_a: Position, pos_b: Position) -> bool:
        piece_a = self._state.board.piece_at(pos_a)
        piece_b = self._state.board.piece_at(pos_b)
        return piece_a is not None and piece_b is not None and piece_a.color == piece_b.color

    def can_select(self, position: Position) -> bool:
        """שער יחיד: game_over + has_piece + is_busy + is_cooling_down - כדי
        שאף קורא לא יצטרך לבדוק game_over בעצמו לפני שהוא שואל 'אפשר
        לבחור את התא הזה?'."""
        if self._state.game_over:
            return False
        return self.has_piece(position) and not self.is_busy(position) and not self.is_cooling_down(position)

    def request_move(self, from_pos: Position, to_pos: Position) -> MoveResult:
        """שערי היישום (game_over, motion_in_progress, cooling_down) קודם -
        לפני שפונים בכלל ל-RuleEngine. רק לאחר ולידציה תקינה מתבצע הביצוע
        עצמו: קודם מקצרים את היעד אם כלי ידידותי "כמעט חוצה" את הדרך
        (truncated_destination), ואז בודקים קונפליקט תזמון מול כלי אויב
        על הדרך *בפועל* (שעשויה להיות מקוצרת) - וזה קורה כאן, לא ב-RuleEngine."""
        if self._state.game_over:
            return MoveResult(is_accepted=False, reason=REASON_GAME_OVER)

        if self.is_busy(from_pos):
            return MoveResult(is_accepted=False, reason=REASON_MOTION_IN_PROGRESS)

        if self.is_cooling_down(from_pos):
            return MoveResult(is_accepted=False, reason=REASON_COOLING_DOWN)

        validation = self._rules.validate_move(from_pos, to_pos)
        if not validation.is_valid:
            return MoveResult(is_accepted=False, reason=validation.reason)

        piece = self._state.board.piece_at(from_pos)

        actual_to = self._arbiter.truncated_destination(piece.color, from_pos, to_pos)
        if actual_to is None:
            return MoveResult(is_accepted=False, reason=REASON_BLOCKED_BY_FRIENDLY_MOTION)

        if self._arbiter.has_route_conflict(piece.color, from_pos, actual_to):
            return MoveResult(is_accepted=False, reason=REASON_ROUTE_CONFLICT)

        if self._arbiter.is_destination_reserved(piece.color, actual_to):
            return MoveResult(is_accepted=False, reason=REASON_DESTINATION_RESERVED)

        self._arbiter.start_motion(piece, actual_to)
        return MoveResult(is_accepted=True, reason=REASON_OK)

    def try_jump(self, position: Position) -> bool:
        """הרחבה מותאמת אישית (מחוץ ל-DSL הרשמי) - ר' plan/README."""
        if self._state.game_over:
            return False
        if not self.has_piece(position):
            return False
        if self.is_busy(position):
            return False
        if self._arbiter.is_cell_airborne(position):
            return False
        self._arbiter.start_jump(position)
        return True

    def wait(self, time_ms: int) -> None:
        if self._state.game_over:
            return
        if self._arbiter.advance_time(time_ms):
            self._state.game_over = True

    def snapshot(self) -> GameSnapshot:
        """תמונת-מצב read-only ל-Renderer/BoardPrinter."""
        return GameSnapshot(
            board=self._state.board,
            game_over=self._state.game_over,
            motions=self._arbiter.motions,
            jumps=self._arbiter.jumps,
            cooldowns=self._arbiter.cooldowns,
        )

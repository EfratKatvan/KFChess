from __future__ import annotations
from dataclasses import dataclass

from kungfu_chess.model.board import Board
from kungfu_chess.model.game_state import GameState
from kungfu_chess.model.position import Position
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter

REASON_STARTED = "started"
REASON_GAME_OVER = "game_over"
REASON_DESTINATION_RESERVED = "destination_reserved"


@dataclass
class MoveResult:
    started: bool
    reason: str


class GameEngine:
    """שכבת התיאום: שומרת את מצב סיום-המשחק (דרך GameState), מאצילה ולידציה
    ל-RuleEngine, ומפעילה תנועות/זמן דרך RealTimeArbiter. לא מכירה פיקסלים
    ולא בחירה."""

    def __init__(self, board: Board, rule_engine: RuleEngine, arbiter: RealTimeArbiter) -> None:
        self._state = GameState(board=board)
        self._rules = rule_engine
        self._arbiter = arbiter

    def is_game_over(self) -> bool:
        return self._state.game_over

    def is_busy(self, position: Position) -> bool:
        return self._arbiter.is_cell_busy(position)

    def has_piece(self, position: Position) -> bool:
        return self._state.board.piece_at(position) is not None

    def is_same_color(self, pos_a: Position, pos_b: Position) -> bool:
        piece_a = self._state.board.piece_at(pos_a)
        piece_b = self._state.board.piece_at(pos_b)
        return piece_a is not None and piece_b is not None and piece_a.color == piece_b.color

    def can_select(self, position: Position) -> bool:
        """שער יחיד: game_over + has_piece + is_busy - כדי שאף קורא לא יצטרך
        לבדוק game_over בעצמו לפני שהוא שואל 'אפשר לבחור את התא הזה?'."""
        if self._state.game_over:
            return False
        return self.has_piece(position) and not self.is_busy(position)

    def request_move(self, from_pos: Position, to_pos: Position) -> MoveResult:
        """מהלך = בקשה. קודם game_over (לא נוגעים ב-RuleEngine אם המשחק כבר נגמר),
        אחר כך ולידציה טהורה דרך RuleEngine, ורק אם היא תקינה - הביצוע עצמו
        (בדיקת קונפליקט תזמון + התחלת תנועה) קורה כאן, לא ב-RuleEngine."""
        if self._state.game_over:
            return MoveResult(started=False, reason=REASON_GAME_OVER)

        validation = self._rules.validate_move(from_pos, to_pos)
        if not validation.is_valid:
            return MoveResult(started=False, reason=validation.reason)

        if self._arbiter.is_destination_reserved(to_pos):
            return MoveResult(started=False, reason=REASON_DESTINATION_RESERVED)

        piece = self._state.board.piece_at(from_pos)
        self._arbiter.start_motion(piece, to_pos)
        return MoveResult(started=True, reason=REASON_STARTED)

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
        if self._arbiter.advance(time_ms):
            self._state.game_over = True

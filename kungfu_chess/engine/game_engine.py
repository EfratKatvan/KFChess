from __future__ import annotations
from typing import Tuple

from kungfu_chess.model.board import Board
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter

MOVE_STARTED = "started"
MOVE_ILLEGAL = "illegal"
MOVE_DESTINATION_RESERVED = "reserved"


class GameEngine:
    """שכבת התיאום: שומרת את מצב סיום-המשחק, מאצילה ולידציה ל-RuleEngine,
    ומפעילה תנועות/זמן דרך RealTimeArbiter. לא מכירה פיקסלים ולא בחירה."""

    def __init__(self, board: Board, rule_engine: RuleEngine, arbiter: RealTimeArbiter) -> None:
        self._board = board
        self._rules = rule_engine
        self._arbiter = arbiter
        self._game_over = False

    def is_game_over(self) -> bool:
        return self._game_over

    def is_busy(self, row: int, col: int) -> bool:
        return self._arbiter.is_cell_busy(row, col)

    def has_piece(self, row: int, col: int) -> bool:
        return self._board.get_cell(row, col) != "."

    def is_same_color(self, pos_a: Tuple[int, int], pos_b: Tuple[int, int]) -> bool:
        token_a = self._board.get_cell(*pos_a)
        token_b = self._board.get_cell(*pos_b)
        return token_a != "." and token_b != "." and token_a[0] == token_b[0]

    def try_move(self, from_pos: Tuple[int, int], to_pos: Tuple[int, int]) -> str:
        if self._game_over:
            return MOVE_ILLEGAL

        piece_token = self._board.get_cell(*from_pos)
        if not self._rules.is_legal_move(piece_token, from_pos, to_pos):
            return MOVE_ILLEGAL

        if self._arbiter.is_destination_reserved(*to_pos):
            return MOVE_DESTINATION_RESERVED

        self._arbiter.start_motion(piece_token, from_pos, to_pos)
        return MOVE_STARTED

    def try_jump(self, row: int, col: int) -> bool:
        """הרחבה מותאמת אישית (מחוץ ל-DSL הרשמי) - ר' plan/README."""
        if self._game_over:
            return False
        if self._board.get_cell(row, col) == ".":
            return False
        if self._arbiter.is_cell_busy(row, col):
            return False
        if self._arbiter.is_cell_airborne(row, col):
            return False
        self._arbiter.start_jump(row, col)
        return True

    def wait(self, time_ms: int) -> None:
        if self._game_over:
            return
        if self._arbiter.advance(time_ms):
            self._game_over = True

    def snapshot_rows(self) -> list[list[str]]:
        return self._board.to_rows()

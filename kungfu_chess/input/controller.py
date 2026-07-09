from __future__ import annotations
from typing import Optional, Tuple

from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.engine.game_engine import GameEngine, MOVE_STARTED, MOVE_DESTINATION_RESERVED


class Controller:
    """מפרש קליקים ומנהל את מצב הבחירה (selected_pos) בלבד.
    לא מחזיק Board, לא בודק חוקיות שחמט, ולא נוגע בלוח - כל שאלה על מצב
    המשחק היא קריאה בשם מפורש ל-GameEngine (השירות), לא קריאה ישירה ללוח."""

    def __init__(self, mapper: BoardMapper, engine: GameEngine) -> None:
        self._mapper = mapper
        self._engine = engine
        self.selected_pos: Optional[Tuple[int, int]] = None

    def handle_click(self, x: int, y: int) -> None:
        if self._engine.is_game_over():
            return

        cell = self._mapper.to_cell(x, y)
        if cell is None:
            return

        if self.selected_pos is None:
            if self._engine.has_piece(*cell) and not self._engine.is_busy(*cell):
                self.selected_pos = cell
            return

        if self.selected_pos == cell:
            return

        if self._engine.is_same_color(self.selected_pos, cell):
            if not self._engine.is_busy(*cell):
                self.selected_pos = cell
            return

        result = self._engine.try_move(self.selected_pos, cell)
        if result in (MOVE_STARTED, MOVE_DESTINATION_RESERVED):
            self.selected_pos = None
        # אם המהלך לא חוקי - הבחירה נשארת כפי שהיא

    def handle_jump(self, x: int, y: int) -> None:
        if self._engine.is_game_over():
            return
        cell = self._mapper.to_cell(x, y)
        if cell is None:
            return
        self._engine.try_jump(*cell)

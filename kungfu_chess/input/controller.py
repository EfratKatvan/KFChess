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
        cell = self._mapper.to_cell(x, y)
        if cell is None:
            return

        #אם לא נבחר תא עדיין-קליק שני, נבדוק אם יש כלי בתא זה ואם הוא פנוי - אם כן, נבחר אותו
        # (can_select כולל בתוכו את בדיקת game_over - אין צורך לבדוק אותה כאן שוב)
        if self.selected_pos is None:
            if self._engine.can_select(*cell):
                self.selected_pos = cell
            return
        #אם תא המקור והיעד שוים, אין צורך לעשות כלום
        if self.selected_pos == cell:
            return

        #אם נבחר כלי של אותו צבע, נבדוק אם הוא פנוי - אם כן, נשנה את הבחירה אליו
        if self._engine.is_same_color(self.selected_pos, cell):
            if self._engine.can_select(*cell):
                self.selected_pos = cell
            return

        # game_over וחוקיות המהלך נבדקים שניהם בתוך try_move - שער יחיד
        result = self._engine.try_move(self.selected_pos, cell)
        if result in (MOVE_STARTED, MOVE_DESTINATION_RESERVED):
            self.selected_pos = None
        # אם המהלך לא חוקי - הבחירה נשארת כפי שהיא

    def handle_jump(self, x: int, y: int) -> None:
        cell = self._mapper.to_cell(x, y)
        if cell is None:
            return
        # game_over נבדק בתוך try_jump - שער יחיד
        self._engine.try_jump(*cell)

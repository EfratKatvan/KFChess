from __future__ import annotations
from dataclasses import dataclass

from kungfu_chess.model.board import Board


@dataclass(frozen=True)
class GameSnapshot:
    """תמונת-מצב read-only של המשחק, מיוצרת ע"י GameEngine עבור צרכנים חיצוניים
    (Renderer, BoardPrinter). לא נועד למוטציה - צרכנים לא אמורים לקרוא
    למתודות שמשנות את ה-board שבפנים."""

    board: Board
    game_over: bool

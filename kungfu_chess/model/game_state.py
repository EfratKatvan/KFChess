from __future__ import annotations
from dataclasses import dataclass

from kungfu_chess.model.board import Board


@dataclass
class GameState:
    """מצב המשחק החי כרגע: הלוח + האם המשחק הסתיים.

    לא יודע כלום על זמן, תנועות פעילות, קלט, ציור, או פרסור טקסט -
    אלה שייכים לשכבות אחרות (RealTimeArbiter, Controller, Renderer, IO)."""

    board: Board
    game_over: bool = False

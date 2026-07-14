from __future__ import annotations
from dataclasses import dataclass, field
from typing import List

from kungfu_chess.model.board import Board
from kungfu_chess.realtime.motion import Cooldown, Jump, Motion


@dataclass(frozen=True)
class GameSnapshot:
    """תמונת-מצב read-only של המשחק, מיוצרת ע"י GameEngine עבור צרכנים חיצוניים
    (Renderer, BoardPrinter). לא נועד למוטציה - צרכנים לא אמורים לקרוא
    למתודות שמשנות את ה-board שבפנים. motions/jumps/cooldowns מאפשרים
    ל-Renderer לדעת אילו אנימציות להציג לכל כלי, בלי לגשת ל-RealTimeArbiter
    ישירות."""

    board: Board
    game_over: bool
    motions: List[Motion] = field(default_factory=list)
    jumps: List[Jump] = field(default_factory=list)
    cooldowns: List[Cooldown] = field(default_factory=list)

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Position:
    """תא לוחי (row, col) - לא פיקסלים, לא אינדקס במערך.

    Position לא בודק גבולות לוח בכוונה - זו אחריות של Board בלבד."""

    row: int
    col: int

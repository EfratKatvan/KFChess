from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Motion:
    """כלי שנמצא בדרך מתא מקור לתא יעד, עם זמן שנותר עד ההגעה."""

    piece_token: str
    from_row: int
    from_col: int
    to_row: int
    to_col: int
    remaining_ms: int


@dataclass
class Jump:
    """הרחבה מותאמת אישית (מחוץ ל-DSL הרשמי): חלון חסינות זמני לכלי בתא נתון."""

    row: int
    col: int
    remaining_ms: int

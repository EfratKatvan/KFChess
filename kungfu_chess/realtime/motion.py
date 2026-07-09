from __future__ import annotations
from dataclasses import dataclass

from kungfu_chess.model.piece import Piece
from kungfu_chess.model.position import Position


@dataclass
class Motion:
    """כלי שנמצא בדרך ליעד, עם זמן שנותר עד ההגעה.

    אין צורך לשמור מיקום מקור בנפרד - piece.cell הוא תמיד המקור הנוכחי,
    כי אף אחד לא זז את אותו piece חוץ מהתנועה הזו עצמה (is_cell_busy מונע
    מהכלי הזה להיבחר לתנועה שנייה בו-זמנית)."""

    piece: Piece
    to_pos: Position
    remaining_ms: int


@dataclass
class Jump:
    """הרחבה מותאמת אישית (מחוץ ל-DSL הרשמי): חלון חסינות זמני לתא נתון."""

    position: Position
    remaining_ms: int

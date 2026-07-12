from __future__ import annotations
from dataclasses import dataclass

from kungfu_chess.model.piece import Piece
from kungfu_chess.model.position import Position

MS_PER_CELL = 1000
_EPSILON = 1e-9


def is_straight_line(source: Position, destination: Position) -> bool:
    """True אם התנועה היא בקו ישר/מאונך/אלכסוני - יש לה מסלול רציף.
    כל דבר אחר (קפיצת-L של סוס) הוא קפיצה בלי מסלול רציף להתנגש עליו,
    בדיוק כמו שסוס כבר מתעלם מחסימות בדרך."""
    row_diff = destination.row - source.row
    col_diff = destination.col - source.col
    return row_diff == 0 or col_diff == 0 or abs(row_diff) == abs(col_diff)


def motion_duration_ms(source: Position, destination: Position) -> int:
    cells = max(abs(destination.row - source.row), abs(destination.col - source.col))
    return cells * MS_PER_CELL


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


@dataclass(frozen=True)
class Trajectory:
    """מסלול קו-ישר במרחב וזמן רציפים: ב-source כש-start_offset_ms חולף
    (יחסית ל"עכשיו"), ב-destination כש-start_offset_ms + duration_ms חולף.
    לתנועה שכבר "באוויר" יש start_offset_ms שלילי (התחילה בעבר); לתנועה
    מבוקשת חדשה start_offset_ms הוא 0."""

    source: Position
    destination: Position
    duration_ms: int
    start_offset_ms: int = 0

    @property
    def end_offset_ms(self) -> int:
        return self.start_offset_ms + self.duration_ms


def trajectories_collide(a: Trajectory, b: Trajectory) -> bool:
    """True אם שני מסלולים ישרים יהיו באותה נקודה בדיוק באותו רגע, אי-שם
    בחלון הזמן שבו שניהם "באוויר" - לא רק אם המסלולים חוצים את אותו תא,
    אלא אם שני הכלים יהיו שם יחד. פותר position_a(t) == position_b(t)
    עבור שורה ועמודה בו-זמנית, מוגבל לחלון הזמן החופף."""
    if a.duration_ms == 0 or b.duration_ms == 0:
        return False

    overlap_start = max(a.start_offset_ms, b.start_offset_ms)
    overlap_end = min(a.end_offset_ms, b.end_offset_ms)
    if overlap_start > overlap_end:
        return False

    row_rate_a = (a.destination.row - a.source.row) / a.duration_ms
    col_rate_a = (a.destination.col - a.source.col) / a.duration_ms
    row_rate_b = (b.destination.row - b.source.row) / b.duration_ms
    col_rate_b = (b.destination.col - b.source.col) / b.duration_ms

    row_coeff = row_rate_a - row_rate_b
    row_offset = (b.source.row - a.source.row) + row_rate_a * a.start_offset_ms - row_rate_b * b.start_offset_ms
    col_coeff = col_rate_a - col_rate_b
    col_offset = (b.source.col - a.source.col) + col_rate_a * a.start_offset_ms - col_rate_b * b.start_offset_ms

    collision_time = None
    if abs(row_coeff) > _EPSILON:
        candidate = row_offset / row_coeff
        if abs(col_coeff) > _EPSILON:
            if abs(col_coeff * candidate - col_offset) < _EPSILON:
                collision_time = candidate
        elif abs(col_offset) < _EPSILON:
            collision_time = candidate
    elif abs(row_offset) < _EPSILON:
        if abs(col_coeff) > _EPSILON:
            collision_time = col_offset / col_coeff
        elif abs(col_offset) < _EPSILON:
            collision_time = overlap_start

    return collision_time is not None and overlap_start - _EPSILON <= collision_time <= overlap_end + _EPSILON

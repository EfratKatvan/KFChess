from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple

from kungfu_chess.model.piece import Piece
from kungfu_chess.model.position import Position

MS_PER_CELL = 1000
_EPSILON = 1e-9

# אם אן חיובי מחיר 1 אם אן שלילי מחזיר -1 אם אן שווה 0 מחזיר 0
def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


#מחזיר אמת אם צריך לבדוק את הסלול בדרך (כלומר, אם התנועה היא בקו ישר/מאונך/אלכסוני).
def is_straight_line(source: Position, destination: Position) -> bool:
    """True אם התנועה היא בקו ישר/מאונך/אלכסוני - יש לה מסלול רציף.
    כל דבר אחר (קפיצת-L של סוס) הוא קפיצה בלי מסלול רציף להתנגש עליו,
    בדיוק כמו שסוס כבר מתעלם מחסימות בדרך."""
    row_diff = destination.row - source.row
    col_diff = destination.col - source.col
    return row_diff == 0 or col_diff == 0 or abs(row_diff) == abs(col_diff)

#מחשב כמה זמן לוקח למהלך
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


SHORT_REST = "short_rest"
LONG_REST = "long_rest"


@dataclass
class Cooldown:
    """חלון זמן שבו כלי שזה עתה נחת בתא הזה "קפוא" - אי אפשר לבחור אותו
    או לבקש עבורו מהלך חדש עד שהזמן שנותר מגיע ל-0. kind מבדיל בין קירור
    אחרי תנועה רגילה (LONG_REST) לקירור אחרי קפיצה (SHORT_REST) - משמש
    ל-Renderer לבחור את האנימציה המתאימה."""

    position: Position
    remaining_ms: int
    kind: str = LONG_REST


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


def _axis_rates(t: Trajectory) -> Tuple[float, float]:
    """קצב שינוי שורה/עמודה של מסלול (יחידות: תאים/מילישניות) - חושב פעם
    אחת ומשותף בין _solve_collision_time ו-collision_position."""
    return (t.destination.row - t.source.row) / t.duration_ms, (t.destination.col - t.source.col) / t.duration_ms

#בודקת אם התנגשות בין שני מסלולים מתרחשת, ואם כן - מחזירה את הזמן שבו זה קורה (יחידות: מילישניות). אחרת מחזירה None.
def _solve_collision_time(a: Trajectory, b: Trajectory) -> Optional[float]:
    """הליבה המשותפת: מוצאת את הרגע (אם קיים) שבו position_a(t) ==
    position_b(t) עבור שורה ועמודה בו-זמנית, בתוך חלון הזמן שבו שני
    המסלולים "באוויר" יחד. ר' trajectories_collide/collision_position
    למשמעות המלאה."""
    if a.duration_ms == 0 or b.duration_ms == 0:
        return None

    #רק בטווח הזמן שבו שניהם "באוויר" - לא רק אם המסלולים חוצים את אותו תא.
    overlap_start = max(a.start_offset_ms, b.start_offset_ms)
    overlap_end = min(a.end_offset_ms, b.end_offset_ms)
    if overlap_start > overlap_end:
        return None

    row_rate_a, col_rate_a = _axis_rates(a)
    row_rate_b, col_rate_b = _axis_rates(b)

    #מה ההבדל בין קצב השורות והעמדות
    row_coeff = row_rate_a - row_rate_b
    row_offset = (b.source.row - a.source.row) + row_rate_a * a.start_offset_ms - row_rate_b * b.start_offset_ms
    col_coeff = col_rate_a - col_rate_b
    col_offset = (b.source.col - a.source.col) + col_rate_a * a.start_offset_ms - col_rate_b * b.start_offset_ms

    #מציאת זמן התנגשות-בו הכלים נמצאים יחד באותו תא
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

    if collision_time is None:
        return None
    in_window = overlap_start - _EPSILON <= collision_time <= overlap_end + _EPSILON
    return collision_time if in_window else None


def trajectories_collide(a: Trajectory, b: Trajectory) -> bool:
    """True אם שני מסלולים ישרים יהיו באותה נקודה בדיוק באותו רגע, אי-שם
    בחלון הזמן שבו שניהם "באוויר" - לא רק אם המסלולים חוצים את אותו תא,
    אלא אם שני הכלים יהיו שם יחד."""
    return _solve_collision_time(a, b) is not None

#אם הם נפגשים, מחזירה את התא שבו הם נפגשים  (מעוגל לתא שלם). אחרת None.
def collision_position(a: Trajectory, b: Trajectory) -> Optional[Position]:
    """אם שני המסלולים מתנגשים (ר' trajectories_collide), מחזירה את התא
    (מעוגל לתא שלם) שבו זה קורה. אחרת None."""
    collision_time = _solve_collision_time(a, b)
    if collision_time is None:
        return None

    row_rate_a, col_rate_a = _axis_rates(a)
    elapsed = collision_time - a.start_offset_ms
    return Position(round(a.source.row + row_rate_a * elapsed), round(a.source.col + col_rate_a * elapsed))

#מחזירה תא אחד לפני ההתנגשות
def truncated_before_collision(requested: Trajectory, active: Trajectory) -> Optional[Position]:
    """אם requested היה מתנגש עם active (ר' collision_position), מחזירה
    את התא אחד לפני נקודת ההתנגשות לאורך הכיוון של requested - התא שבו
    requested "נתקע" במקום להמשיך. עשויה להחזיר את requested.source עצמו
    אם ההתנגשות קורית כבר בצעד הראשון (אין יעד חוקי בכיוון הזה). None
    אם אין התנגשות בכלל."""
    point = collision_position(requested, active)

    #אם אין התנגשות או שההתנגשות היא כבר בצעד הראשון - אין יעד חוקי.
    if point is None or point == requested.source:
        return None

    #אם יש התנגשות, מחזירה את התא אחד לפני נקודת ההתנגשות לאורך הכיוון של requested - התא שבו requested "נתקע" במקום להמשיך.
    row_step = _sign(requested.destination.row - requested.source.row)
    col_step = _sign(requested.destination.col - requested.source.col)
    return Position(point.row - row_step, point.col - col_step)

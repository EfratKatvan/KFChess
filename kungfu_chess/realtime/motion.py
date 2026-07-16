from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple

from kungfu_chess.assets_config import DEFAULT_PIECE_SET, load_state_config
from kungfu_chess.model.piece import Piece
from kungfu_chess.model.position import Position

# Reads physics.* for real from CTD26's config.json - not hand-copied
# numbers. Move speed (state "move") is uniform across all piece kinds
# (pieces1 and pieces2 alike), so we read one representative example
# (white pawn) instead of threading "which piece" through every
# collision-detection function, which today only knows Position, not Piece.
_PHYSICS_REFERENCE_ASSET_CODE = "PW"
_move_physics = load_state_config(_PHYSICS_REFERENCE_ASSET_CODE, "move", DEFAULT_PIECE_SET)["physics"]
_jump_physics = load_state_config(_PHYSICS_REFERENCE_ASSET_CODE, "jump", DEFAULT_PIECE_SET)["physics"]

# "Meter" isn't defined anywhere else in CTD26 - we set the conversion
# ratio between board cell and meter ourselves: one square = one meter.
METERS_PER_CELL = 1.0
MOVE_SPEED_M_PER_SEC = _move_physics["speed_m_per_sec"]
MS_PER_CELL = round(METERS_PER_CELL / MOVE_SPEED_M_PER_SEC * 1000)

# Not our own arbitrary choice - read for real from config.json (physics.next_state_when_finished)
MOVE_NEXT_STATE = _move_physics["next_state_when_finished"]  # "long_rest"
JUMP_NEXT_STATE = _jump_physics["next_state_when_finished"]  # "short_rest"

_EPSILON = 1e-9

def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


def is_straight_line(source: Position, destination: Position) -> bool:
    """Anything that isn't a straight/perpendicular/diagonal line
    (a knight's L-jump) is a jump with no continuous path to collide
    along, exactly like a knight already ignores blockers in its way."""
    row_diff = destination.row - source.row
    col_diff = destination.col - source.col
    return row_diff == 0 or col_diff == 0 or abs(row_diff) == abs(col_diff)


def motion_duration_ms(source: Position, destination: Position) -> int:
    cells = max(abs(destination.row - source.row), abs(destination.col - source.col))
    return cells * MS_PER_CELL


@dataclass
class Motion:
    """A piece on its way to a destination, with the time left until
    arrival.

    No need to store a source position separately - piece.cell is
    always the current source, since nothing else moves that same piece
    while this motion is active (is_piece_in_motion prevents this piece
    from being selected for a second, simultaneous motion)."""

    piece: Piece
    to_pos: Position
    remaining_ms: int


@dataclass
class Jump:
    """A custom extension (outside the official DSL): a temporary
    immunity window for a given cell."""

    position: Position
    remaining_ms: int


SHORT_REST = "short_rest"
LONG_REST = "long_rest"


@dataclass
class Cooldown:
    """A time window during which a piece that just landed on this cell
    is "frozen" - it can't be selected or given a new move until the
    time remaining reaches 0. kind distinguishes cooldown after an
    ordinary move (LONG_REST) from cooldown after a jump (SHORT_REST) -
    used by the Renderer to pick the right animation."""

    position: Position
    remaining_ms: int
    kind: str = LONG_REST


@dataclass(frozen=True)
class Trajectory:
    """A straight-line path through continuous space and time: at
    source when start_offset_ms has elapsed (relative to "now"), at
    destination when start_offset_ms + duration_ms has elapsed. A
    motion already "in the air" has a negative start_offset_ms (it
    started in the past); a newly requested motion has start_offset_ms
    of 0."""

    source: Position
    destination: Position
    duration_ms: int
    start_offset_ms: int = 0

    @property
    def end_offset_ms(self) -> int:
        return self.start_offset_ms + self.duration_ms


def _axis_rates(t: Trajectory) -> Tuple[float, float]:
    """A trajectory's row/column rate of change (units: cells/ms) -
    computed once and shared between _solve_collision_time and
    collision_position."""
    return (t.destination.row - t.source.row) / t.duration_ms, (t.destination.col - t.source.col) / t.duration_ms

def _solve_collision_time(a: Trajectory, b: Trajectory) -> Optional[float]:
    """The shared core for trajectories_collide/collision_position."""
    if a.duration_ms == 0 or b.duration_ms == 0:
        return None

    # Only within the time window where both are "in the air" - not just where the paths cross the same cell.
    overlap_start = max(a.start_offset_ms, b.start_offset_ms)
    overlap_end = min(a.end_offset_ms, b.end_offset_ms)
    if overlap_start > overlap_end:
        return None

    row_rate_a, col_rate_a = _axis_rates(a)
    row_rate_b, col_rate_b = _axis_rates(b)

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

    if collision_time is None:
        return None
    in_window = overlap_start - _EPSILON <= collision_time <= overlap_end + _EPSILON
    return collision_time if in_window else None


def trajectories_collide(a: Trajectory, b: Trajectory) -> bool:
    """True if two straight trajectories will be at the exact same point
    at the exact same moment, somewhere in the time window where both
    are "in the air" - not just whether the paths cross the same cell,
    but whether both pieces will be there together."""
    return _solve_collision_time(a, b) is not None

def collision_position(a: Trajectory, b: Trajectory) -> Optional[Position]:
    """Rounded to a whole cell - must point to a valid Position on the
    board, not a fractional point mid-path."""
    collision_time = _solve_collision_time(a, b)
    if collision_time is None:
        return None

    row_rate_a, col_rate_a = _axis_rates(a)
    elapsed = collision_time - a.start_offset_ms
    return Position(round(a.source.row + row_rate_a * elapsed), round(a.source.col + col_rate_a * elapsed))

def truncated_before_collision(requested: Trajectory, active: Trajectory) -> Optional[Position]:
    """The piece "gets stuck" one cell before the collision point,
    instead of continuing - may return requested.source itself if the
    collision happens already on the first step (no legal destination
    in that direction)."""
    point = collision_position(requested, active)

    if point is None or point == requested.source:
        return None

    row_step = _sign(requested.destination.row - requested.source.row)
    col_step = _sign(requested.destination.col - requested.source.col)
    return Position(point.row - row_step, point.col - col_step)

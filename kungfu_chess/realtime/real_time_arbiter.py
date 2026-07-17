from __future__ import annotations
from typing import List, Optional

from kungfu_chess.model.board import BoardRepresentation
from kungfu_chess.model.game_state import GameObserver, PieceCapturedEvent
from kungfu_chess.model.piece import PieceRepresentation, IDLE, MOVING, CAPTURED
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.motion import (
    JUMP_NEXT_STATE,
    MOVE_NEXT_STATE,
    Cooldown,
    Jump,
    Motion,
    Trajectory,
    is_straight_line,
    motion_duration_ms,
    trajectories_collide,
    truncated_before_collision,
)
from kungfu_chess.rules.rule_engine import (
    KingCaptureWinCondition,
    LastRankPromotion,
    PromotionRule,
    WinCondition,
)
from kungfu_chess.rules.scoring import piece_value

JUMP_DURATION_MS = 1000
COOLDOWN_DURATION_MS = 3000
SHORT_REST_DURATION_MS = 3000


def _active_trajectory(motion: Motion) -> Optional[Trajectory]:
    """Builds the current Trajectory of an active motion - None if it's
    not straight (a knight's L-jump, which has no continuous path to
    collide along)."""
    source = motion.piece.cell
    if not is_straight_line(source, motion.to_pos):
        return None
    duration = motion_duration_ms(source, motion.to_pos)
    elapsed = duration - motion.remaining_ms
    return Trajectory(source, motion.to_pos, duration, start_offset_ms=-elapsed)


class RealTimeArbiter:
    """Manages the active motions and jumps, and advances them as time
    passes.

    Arrival, capture, and king-capture-detection logic matches 1:1 the
    behavior that used to live in GameController._handle_wait, including
    the immediate stop of all further processing (and skipping the jump
    update) the moment a king is captured. What ends the game
    (WinCondition) and what happens on arrival (PromotionRule) are
    swappable from outside.
    """

    def __init__(
        self,
        board: BoardRepresentation,
        win_condition: Optional[WinCondition] = None,
        promotion_rule: Optional[PromotionRule] = None,
    ) -> None:
        self._board = board
        self._motions: List[Motion] = []
        self._jumps: List[Jump] = []
        self._cooldowns: List[Cooldown] = []
        self._observers: List[GameObserver] = []
        self._win_condition = win_condition if win_condition is not None else KingCaptureWinCondition()
        self._promotion_rule = promotion_rule if promotion_rule is not None else LastRankPromotion()

    def add_observer(self, observer: GameObserver) -> None:
        """Registers something that wants to react to a capture as it
        resolves - see GameEngine.add_observer, the single public entry
        point callers actually use (it forwards here too)."""
        self._observers.append(observer)

    @property
    def motions(self) -> List[Motion]:
        return list(self._motions)

    @property
    def jumps(self) -> List[Jump]:
        return list(self._jumps)

    @property
    def cooldowns(self) -> List[Cooldown]:
        return list(self._cooldowns)

    def is_piece_in_motion(self, position: Position) -> bool:
        """True only if the piece currently sitting at position is
        already mid-motion itself - and can't be selected/moved/jumped
        again until it arrives. Intentionally does *not* check whether
        position is the destination of an incoming motion by another
        piece: a piece that's merely under attack (hasn't itself moved
        yet) must remain selectable so it can flee before the attacker
        lands - see _resolve_arrival, which already supports a victim
        piece that fled in time."""
        return any(m.piece.cell == position for m in self._motions)

    # Opposite-color pieces CAN compete for the same destination - see
    # advance_time; whoever arrives later eats whoever arrived earlier.
    def is_destination_reserved(self, color: str, position: Position) -> bool:
        return any(m.to_pos == position and m.piece.color == color for m in self._motions)

    # Jumps aren't counted as busy (is_piece_in_motion) - they have their own immunity check.
    def is_cell_airborne(self, position: Position) -> bool:
        return any(j.position == position and j.remaining_ms > 0 for j in self._jumps)

    def is_cell_cooling_down(self, position: Position) -> bool:
        return any(c.position == position and c.remaining_ms > 0 for c in self._cooldowns)

    def has_route_conflict(self, color: str, from_pos: Position, to_pos: Position) -> bool:
        """True if an opposite-color piece is already in motion right
        now, and both pieces would be at the exact same point at the
        exact same moment (a continuous-time model - see
        realtime/motion.py), not just if the paths cross the same cell.
        Same-color pieces never block each other. Non-straight motions
        (a knight's jump) are exempt - they have no continuous path."""
        if not is_straight_line(from_pos, to_pos):
            return False

        requested = Trajectory(from_pos, to_pos, motion_duration_ms(from_pos, to_pos))

        for motion in self._motions:
            if motion.piece.color == color:
                continue

            active = _active_trajectory(motion)
            if active is None:
                continue

            if trajectories_collide(requested, active):
                return True

        return False

    def truncated_destination(self, color: str, from_pos: Position, to_pos: Position) -> Optional[Position]:
        """If several collisions are possible, picks the closest one to
        the source - that's the first one the piece would actually get
        stuck at."""
        if not is_straight_line(from_pos, to_pos):
            return to_pos

        requested = Trajectory(from_pos, to_pos, motion_duration_ms(from_pos, to_pos))

        cutoffs = []
        for motion in self._motions:
            if motion.piece.color != color:
                continue

            active = _active_trajectory(motion)
            if active is None:
                continue

            cutoff = truncated_before_collision(requested, active)
            if cutoff is not None:
                cutoffs.append(cutoff)

        if not cutoffs:
            return to_pos
        
        closest = min(cutoffs, key=lambda c: max(abs(c.row - from_pos.row), abs(c.col - from_pos.col)))
        return None if closest == from_pos else closest

    def start_motion(self, piece: PieceRepresentation, to_pos: Position) -> None:
        from_pos = piece.cell
        travel_time = motion_duration_ms(from_pos, to_pos)
        piece.state = MOVING
        self._motions.append(Motion(piece, to_pos, travel_time))

    def start_jump(self, position: Position) -> None:
        self._jumps.append(Jump(position, JUMP_DURATION_MS))

    def advance_time(self, time_ms: int) -> bool:
        """Advances time by time_ms. Returns True if a king was captured
        this round. Processes motions that finish on the same tick in
        chronological arrival order (whoever had less remaining_ms
        arrives first) - so if two pieces arrive at the same destination
        on the same tick, whoever gets there first is already sitting
        there when the second one arrives (and then gets captured
        naturally through ordinary capture logic, not separate handling).
        Advances existing cooldowns *before* processing arrivals - so a
        cooldown newly created by an arrival on this same tick isn't
        immediately trimmed within the same call."""
        self._advance_cooldowns(time_ms)

        new_motions: List[Motion] = []
        for motion in sorted(self._motions, key=lambda m: m.remaining_ms):
            remaining = motion.remaining_ms - time_ms
            if remaining > 0:
                new_motions.append(Motion(motion.piece, motion.to_pos, remaining))
                continue

            if self._resolve_arrival(motion):
                self._motions = []
                return True

        self._motions = new_motions
        self._advance_jumps(time_ms)
        return False

    def _resolve_arrival(self, motion: Motion) -> bool:
        """Returns True if a king was captured - including an airborne
        capture, not just a normal landing."""
        piece = motion.piece

        if piece.state == CAPTURED:
            # The piece was already captured elsewhere (e.g. an enemy
            # piece successfully attacked its source cell while it was
            # still "in flight" from there - is_destination_reserved
            # doesn't protect against this, since it only checks other
            # motions' destinations, not sources). Its motion is
            # cancelled - there's nothing to land, the piece no longer exists.
            return False

        from_pos = piece.cell
        to_pos = motion.to_pos

        if self.is_cell_airborne(to_pos):
            # The moving piece is "swallowed" mid-air - the piece that
            # jumped stays in place, and gets points for destroying the
            # piece that tried to attack it (just like an ordinary capture).
            defender = self._board.piece_at(to_pos)
            if defender is not None:
                self._notify_captured(defender.color, piece.kind)
            if self._board.piece_at(from_pos) is piece:
                self._board.remove_piece(piece)
            return self._win_condition.is_game_over(piece)

        captured = self._board.piece_at(to_pos)

        # Vacate the source cell only if the piece is actually still
        # there (it could have already been captured there by another
        # motion that finished on the same tick - see realtime/motion.py)
        if self._board.piece_at(from_pos) is piece:
            self._board.remove_piece(piece)

        if captured is not None:
            self._board.remove_piece(captured)
            captured.state = CAPTURED
            self._notify_captured(piece.color, captured.kind)

        piece.cell = to_pos
        piece.state = IDLE
        self._board.add_piece(piece)
        self._promotion_rule.promote(piece, self._board.height)
        self._cooldowns.append(Cooldown(to_pos, COOLDOWN_DURATION_MS, kind=MOVE_NEXT_STATE))

        return self._win_condition.is_game_over(captured)

    def _notify_captured(self, color: str, destroyed_kind: str) -> None:
        event = PieceCapturedEvent(color, destroyed_kind, piece_value(destroyed_kind))
        for observer in self._observers:
            observer.on_piece_captured(event)

    def _advance_jumps(self, time_ms: int) -> None:
        new_jumps: List[Jump] = []
        for jump in self._jumps:
            remaining = jump.remaining_ms - time_ms
            if remaining > 0:
                new_jumps.append(Jump(jump.position, remaining))
            else:
                self._cooldowns.append(Cooldown(jump.position, SHORT_REST_DURATION_MS, kind=JUMP_NEXT_STATE))
        self._jumps = new_jumps

    def _advance_cooldowns(self, time_ms: int) -> None:
        new_cooldowns: List[Cooldown] = []
        for cooldown in self._cooldowns:
            remaining = cooldown.remaining_ms - time_ms
            if remaining > 0:
                new_cooldowns.append(Cooldown(cooldown.position, remaining))
        self._cooldowns = new_cooldowns

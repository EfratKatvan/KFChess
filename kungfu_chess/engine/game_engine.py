from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from kungfu_chess.engine.board_view_state import BoardViewState, MoveLogEntry, build_board_view_state
from kungfu_chess.model.board import BoardRepresentation
from kungfu_chess.model.game_state import GameObserver, GameState, MoveLoggedEvent
from kungfu_chess.model.position import Position
from kungfu_chess.rules.rule_engine import RuleEngine, REASON_OK
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter

REASON_GAME_OVER = "game_over"
REASON_MOTION_IN_PROGRESS = "motion_in_progress"
REASON_DESTINATION_RESERVED = "destination_reserved"
REASON_ROUTE_CONFLICT = "route_conflict"
REASON_BLOCKED_BY_FRIENDLY_MOTION = "blocked_by_friendly_motion"
REASON_COOLING_DOWN = "cooling_down"


@dataclass
class MoveResult:
    is_accepted: bool
    reason: str


class GameEngine:
    """The coordination layer (Application Service): the public boundary
    through which Controller and TextTestRunner request actions. Holds
    GameState (including game_over), delegates pure validation to
    RuleEngine, and drives motions/time through RealTimeArbiter. Knows
    nothing about pixels, drawing, text parsing, or piece-movement
    logic."""

    def __init__(self, board: BoardRepresentation, rule_engine: RuleEngine, arbiter: RealTimeArbiter) -> None:
        self._state = GameState(board=board)
        self._rules = rule_engine
        self._arbiter = arbiter
        self._total_elapsed_ms = 0
        self._observers: List[GameObserver] = []

    def add_observer(self, observer: GameObserver) -> None:
        """Registers something that wants to react to game events
        (a completed move request, or a resolved capture) without this
        class - or RealTimeArbiter - holding that data itself. A single
        call reaches both event sources, so callers don't need to know
        move events and capture events actually come from two different
        objects - see model.game_state.GameObserver."""
        self._observers.append(observer)
        self._arbiter.add_observer(observer)

    def is_game_over(self) -> bool:
        return self._state.game_over

    def is_busy(self, position: Position) -> bool:
        return self._arbiter.is_piece_in_motion(position)

    def is_cooling_down(self, position: Position) -> bool:
        return self._arbiter.is_cell_cooling_down(position)

    def has_piece(self, position: Position) -> bool:
        return self._state.board.piece_at(position) is not None

    def is_same_color(self, pos_a: Position, pos_b: Position) -> bool:
        piece_a = self._state.board.piece_at(pos_a)
        piece_b = self._state.board.piece_at(pos_b)
        return piece_a is not None and piece_b is not None and piece_a.color == piece_b.color

    def can_select(self, position: Position) -> bool:
        """Single gate: game_over + has_piece + is_busy + is_cooling_down -
        so no caller needs to check game_over itself before asking "can
        I select this cell?"."""
        if self._state.game_over:
            return False
        return self.has_piece(position) and not self.is_busy(position) and not self.is_cooling_down(position)

    def legal_destinations(self, position: Position) -> Set[Position]:
        """Doesn't check real-time blocking (that's moment-dependent, not
        "what was legal at the moment of selection")."""
        if self._state.game_over:
            return set()
        return self._rules.legal_destinations(position)

    def request_move(self, from_pos: Position, to_pos: Position) -> MoveResult:
        """Application-level gates (game_over, motion_in_progress,
        cooling_down) first - before even reaching RuleEngine. Only once
        validation passes does the actual execution happen: first the
        destination is truncated if a friendly piece "almost crosses"
        the path (truncated_destination), then a timing conflict with an
        enemy piece is checked against the *actual* path (which may now
        be truncated) - and that happens here, not in RuleEngine."""
        if self._state.game_over:
            return MoveResult(is_accepted=False, reason=REASON_GAME_OVER)

        if self.is_busy(from_pos):
            return MoveResult(is_accepted=False, reason=REASON_MOTION_IN_PROGRESS)

        if self.is_cooling_down(from_pos):
            return MoveResult(is_accepted=False, reason=REASON_COOLING_DOWN)

        validation = self._rules.validate_move(from_pos, to_pos)
        if not validation.is_valid:
            return MoveResult(is_accepted=False, reason=validation.reason)

        piece = self._state.board.piece_at(from_pos)

        actual_to = self._arbiter.truncated_destination(piece.color, from_pos, to_pos)
        if actual_to is None:
            return MoveResult(is_accepted=False, reason=REASON_BLOCKED_BY_FRIENDLY_MOTION)

        if self._arbiter.has_route_conflict(piece.color, from_pos, actual_to):
            return MoveResult(is_accepted=False, reason=REASON_ROUTE_CONFLICT)

        if self._arbiter.is_destination_reserved(piece.color, actual_to):
            return MoveResult(is_accepted=False, reason=REASON_DESTINATION_RESERVED)

        is_capture = self._state.board.piece_at(actual_to) is not None
        self._arbiter.start_motion(piece, actual_to)
        event = MoveLoggedEvent(
            piece.color, from_pos, actual_to, piece.kind, is_capture, self._total_elapsed_ms
        )
        for observer in self._observers:
            observer.on_move_logged(event)
        return MoveResult(is_accepted=True, reason=REASON_OK)

    def try_jump(self, position: Position) -> bool:
        """A custom extension (outside the official DSL) - see plan/README."""
        if self._state.game_over:
            return False
        if not self.has_piece(position):
            return False
        if self.is_busy(position):
            return False
        if self.is_cooling_down(position):
            return False
        if self._arbiter.is_cell_airborne(position):
            return False
        self._arbiter.start_jump(position)
        return True

    def wait(self, time_ms: int) -> None:
        self._total_elapsed_ms += time_ms
        if self._state.game_over:
            return
        if self._arbiter.advance_time(time_ms):
            self._state.game_over = True

    def snapshot(
        self,
        move_log: Optional[Dict[str, Tuple[MoveLogEntry, ...]]] = None,
        scores: Optional[Dict[str, int]] = None,
    ) -> BoardViewState:
        """move_log/scores both come from the caller (see
        view/observers.py's MoveLogObserver/ScoreObserver) - this class
        fires MoveLoggedEvent on request_move and RealTimeArbiter fires
        PieceCapturedEvent on a resolved capture, but neither stores that
        history itself, so there's nothing of the kind to put here."""
        # Separates the logic layer from the view - returns a DTO, not real Board/Piece objects
        return build_board_view_state(
            board=self._state.board,
            arbiter=self._arbiter,
            game_over=self._state.game_over,
            total_elapsed_ms=self._total_elapsed_ms,
            move_log=move_log,
            scores=scores,
        )

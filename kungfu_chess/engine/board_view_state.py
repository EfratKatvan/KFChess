from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import IDLE as IDLE_STATE
from kungfu_chess.model.piece import Piece
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.motion import SHORT_REST, motion_duration_ms
from kungfu_chess.realtime.real_time_arbiter import (
    COOLDOWN_DURATION_MS,
    JUMP_DURATION_MS,
    SHORT_REST_DURATION_MS,
    RealTimeArbiter,
)

MOVE_STATE = "move"
JUMP_STATE = "jump"


@dataclass(frozen=True)
class PieceView:
    """A minimal, read-only representation of a piece for the view - not
    a real Piece. No id here, and no way to mutate or move anything
    through it - only what's needed to draw: where, which piece, and in
    what visual state."""

    position: Position
    color: str
    kind: str
    visual_state: str
    elapsed_ms: int
    target_position: Optional[Position] = None
    progress: Optional[float] = None
    remaining_fraction: Optional[float] = None


@dataclass(frozen=True)
class MoveLogEntry:
    """A single completed move request, for the per-team move-log panel."""

    elapsed_ms: int
    from_pos: Position
    to_pos: Position


@dataclass(frozen=True)
class BoardViewState:
    """A complete, read-only state snapshot for the view - the "display
    board" separate from the "game board" (the real Board). This is
    everything the view gets; it's never exposed to the real
    Board/Piece/Motion/Jump/Cooldown at all."""

    width: int
    height: int
    game_over: bool
    pieces: Tuple[PieceView, ...] = field(default_factory=tuple)
    scores: Dict[str, int] = field(default_factory=dict)
    move_log: Dict[str, Tuple[MoveLogEntry, ...]] = field(default_factory=dict)


def _resolve_piece_view(piece: Piece, arbiter: RealTimeArbiter, total_elapsed_ms: int) -> PieceView:
    """The check order (jump -> motion -> cooldown -> idle) matches the
    fact that a piece can never be in a jump and a motion at once
    (RealTimeArbiter blocks that) - there's no ambiguity about which
    state "wins"."""
    for jump in arbiter.jumps:
        if jump.position == piece.cell:
            elapsed_ms = JUMP_DURATION_MS - jump.remaining_ms
            return PieceView(
                position=piece.cell, color=piece.color, kind=piece.kind,
                visual_state=JUMP_STATE, elapsed_ms=elapsed_ms,
            )

    for motion in arbiter.motions:
        if motion.piece.id == piece.id:
            duration = motion_duration_ms(piece.cell, motion.to_pos)
            elapsed_ms = duration - motion.remaining_ms
            progress = elapsed_ms / duration if duration > 0 else 1.0
            return PieceView(
                position=piece.cell, color=piece.color, kind=piece.kind,
                visual_state=MOVE_STATE, elapsed_ms=elapsed_ms,
                target_position=motion.to_pos, progress=progress,
            )

    for cooldown in arbiter.cooldowns:
        if cooldown.position == piece.cell:
            full_duration = SHORT_REST_DURATION_MS if cooldown.kind == SHORT_REST else COOLDOWN_DURATION_MS
            elapsed_ms = full_duration - cooldown.remaining_ms
            remaining_fraction = max(0.0, min(1.0, (full_duration - elapsed_ms) / full_duration))
            return PieceView(
                position=piece.cell, color=piece.color, kind=piece.kind,
                visual_state=cooldown.kind, elapsed_ms=elapsed_ms,
                remaining_fraction=remaining_fraction,
            )

    return PieceView(
        position=piece.cell, color=piece.color, kind=piece.kind,
        visual_state=IDLE_STATE, elapsed_ms=total_elapsed_ms,
    )


def build_board_view_state(
    board: Board,
    arbiter: RealTimeArbiter,
    game_over: bool,
    total_elapsed_ms: int,
    move_log: Optional[Dict[str, Tuple[MoveLogEntry, ...]]] = None,
) -> BoardViewState:
    pieces = []
    for row in range(board.height):
        for col in range(board.width):
            piece = board.piece_at(Position(row, col))
            if piece is None:
                continue
            pieces.append(_resolve_piece_view(piece, arbiter, total_elapsed_ms))

    return BoardViewState(
        width=board.width, height=board.height, game_over=game_over,
        pieces=tuple(pieces), scores=arbiter.scores, move_log=move_log or {},
    )

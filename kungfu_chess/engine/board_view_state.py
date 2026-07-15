from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

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
    """ייצוג read-only, מינימלי, של כלי בשביל ה-view - לא Piece אמיתי.
    אין כאן id, ואין דרך למוטט/להזיז שום דבר דרך זה - רק מה שנדרש כדי
    לצייר: איפה, איזה כלי, ובאיזה state ויזואלי."""

    position: Position
    color: str
    kind: str
    visual_state: str
    elapsed_ms: int
    target_position: Optional[Position] = None
    progress: Optional[float] = None
    remaining_fraction: Optional[float] = None


@dataclass(frozen=True)
class BoardViewState:
    """תמונת-מצב read-only שלמה בשביל ה-view - "לוח התצוגה" הנפרד מ-"לוח
    המשחק" (Board האמיתי). זה כל מה שה-view מקבל; הוא לא נחשף בכלל
    ל-Board/Piece/Motion/Jump/Cooldown האמיתיים."""

    width: int
    height: int
    game_over: bool
    pieces: Tuple[PieceView, ...] = field(default_factory=tuple)


def _resolve_piece_view(piece: Piece, arbiter: RealTimeArbiter, total_elapsed_ms: int) -> PieceView:
    """מכונת-המצבים: הופכת Piece.state (בקנד) + Motion/Jump/Cooldown
    (ה-arbiter) ל-piece_state ויזואלי אחד (idle/move/jump/short_rest/
    long_rest). זו בדיוק נקודת-הגבול שבה מידע בקנד מתורגם למה שה-GUI
    צריך לדעת - לא יותר. סדר הבדיקה (קפיצה -> תנועה -> קירור -> idle)
    תואם לכך שכלי לא יכול להיות בו-זמנית בקפיצה ובתנועה (RealTimeArbiter
    חוסם את זה) - אין דו-משמעות איזה state "מנצח"."""
    for jump in arbiter.jumps:
        if jump.position == piece.cell:
            elapsed_ms = JUMP_DURATION_MS - jump.remaining_ms
            return PieceView(piece.cell, piece.color, piece.kind, JUMP_STATE, elapsed_ms)

    for motion in arbiter.motions:
        if motion.piece.id == piece.id:
            duration = motion_duration_ms(piece.cell, motion.to_pos)
            elapsed_ms = duration - motion.remaining_ms
            progress = elapsed_ms / duration if duration > 0 else 1.0
            return PieceView(
                piece.cell, piece.color, piece.kind, MOVE_STATE, elapsed_ms,
                target_position=motion.to_pos, progress=progress,
            )

    for cooldown in arbiter.cooldowns:
        if cooldown.position == piece.cell:
            full_duration = SHORT_REST_DURATION_MS if cooldown.kind == SHORT_REST else COOLDOWN_DURATION_MS
            elapsed_ms = full_duration - cooldown.remaining_ms
            remaining_fraction = max(0.0, min(1.0, (full_duration - elapsed_ms) / full_duration))
            return PieceView(
                piece.cell, piece.color, piece.kind, cooldown.kind, elapsed_ms,
                remaining_fraction=remaining_fraction,
            )

    return PieceView(piece.cell, piece.color, piece.kind, IDLE_STATE, total_elapsed_ms)


def build_board_view_state(
    board: Board, arbiter: RealTimeArbiter, game_over: bool, total_elapsed_ms: int
) -> BoardViewState:
    pieces = []
    for row in range(board.height):
        for col in range(board.width):
            piece = board.piece_at(Position(row, col))
            if piece is None:
                continue
            pieces.append(_resolve_piece_view(piece, arbiter, total_elapsed_ms))

    return BoardViewState(width=board.width, height=board.height, game_over=game_over, pieces=tuple(pieces))

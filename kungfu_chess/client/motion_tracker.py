from __future__ import annotations

from dataclasses import replace
from typing import Dict

from kungfu_chess.client.client_state import PendingMotion
from kungfu_chess.engine.board_view_state import MOVE_STATE, BoardViewState
from kungfu_chess.model.position import Position

"""Client-side render-time interpolation (Server_Design.md section 8):
turns a locally-tracked PendingMotion into an overridden PieceView so
Renderer/BoardView - which already treat target_position/progress/
visual_state/elapsed_ms as pure inputs - draw a smooth glide between
the periodic full snapshots, instead of waiting for the server to
resend progress on every tick."""


def apply_pending_motions(
    view_state: BoardViewState, pending_motions: Dict[Position, PendingMotion], now: float
) -> BoardViewState:
    """Returns a BoardViewState with any actively-moving piece's
    target_position/progress/visual_state/elapsed_ms overridden from
    local elapsed time rather than the (now much staler) values the
    last StateMessage carried for it. A piece with no active pending
    motion - or one whose declared duration has already elapsed - is
    left exactly as the server sent it."""
    if not pending_motions:
        return view_state
    pieces = []
    for piece_view in view_state.pieces:
        motion = pending_motions.get(piece_view.position)
        if motion is not None:
            elapsed_ms = (now - motion.started_at) * 1000
            if elapsed_ms < motion.duration_ms:
                piece_view = replace(
                    piece_view,
                    target_position=motion.to_position,
                    progress=max(0.0, min(1.0, elapsed_ms / motion.duration_ms)),
                    visual_state=MOVE_STATE,
                    elapsed_ms=int(elapsed_ms),
                )
        pieces.append(piece_view)
    return replace(view_state, pieces=tuple(pieces))

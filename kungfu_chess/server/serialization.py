from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from kungfu_chess.engine.board_view_state import BoardViewState, MoveLogEntry, PieceView
from kungfu_chess.model.position import Position

"""Converts the DTOs in engine/board_view_state.py to/from plain JSON-
serializable dicts/lists, so a client (which never imports engine/model
directly) can reconstruct the exact same typed dataclasses Renderer.draw()
already expects - no parallel wire representation to keep in sync."""


def position_to_wire(position: Optional[Position]) -> Optional[List[int]]:
    if position is None:
        return None
    return [position.row, position.col]


def position_from_wire(value: Optional[List[int]]) -> Optional[Position]:
    if value is None:
        return None
    row, col = value
    return Position(row, col)


def piece_view_to_wire(piece_view: PieceView) -> Dict[str, Any]:
    return {
        "position": position_to_wire(piece_view.position),
        "color": piece_view.color,
        "kind": piece_view.kind,
        "visual_state": piece_view.visual_state,
        "elapsed_ms": piece_view.elapsed_ms,
        "target_position": position_to_wire(piece_view.target_position),
        "progress": piece_view.progress,
        "remaining_fraction": piece_view.remaining_fraction,
    }


def piece_view_from_wire(data: Dict[str, Any]) -> PieceView:
    return PieceView(
        position=position_from_wire(data["position"]),
        color=data["color"],
        kind=data["kind"],
        visual_state=data["visual_state"],
        elapsed_ms=data["elapsed_ms"],
        target_position=position_from_wire(data["target_position"]),
        progress=data["progress"],
        remaining_fraction=data["remaining_fraction"],
    )


def move_log_entry_to_wire(entry: MoveLogEntry) -> Dict[str, Any]:
    return {
        "elapsed_ms": entry.elapsed_ms,
        "from_pos": position_to_wire(entry.from_pos),
        "to_pos": position_to_wire(entry.to_pos),
        "kind": entry.kind,
        "is_capture": entry.is_capture,
    }


def move_log_entry_from_wire(data: Dict[str, Any]) -> MoveLogEntry:
    return MoveLogEntry(
        elapsed_ms=data["elapsed_ms"],
        from_pos=position_from_wire(data["from_pos"]),
        to_pos=position_from_wire(data["to_pos"]),
        kind=data["kind"],
        is_capture=data["is_capture"],
    )


def board_view_state_to_wire(state: BoardViewState) -> Dict[str, Any]:
    return {
        "width": state.width,
        "height": state.height,
        "game_over": state.game_over,
        "pieces": [piece_view_to_wire(p) for p in state.pieces],
        "scores": dict(state.scores),
        "move_log": {
            color: [move_log_entry_to_wire(e) for e in entries]
            for color, entries in state.move_log.items()
        },
    }


def board_view_state_from_wire(data: Dict[str, Any]) -> BoardViewState:
    return BoardViewState(
        width=data["width"],
        height=data["height"],
        game_over=data["game_over"],
        pieces=tuple(piece_view_from_wire(p) for p in data["pieces"]),
        scores=dict(data["scores"]),
        move_log={
            color: tuple(move_log_entry_from_wire(e) for e in entries)
            for color, entries in data["move_log"].items()
        },
    )


def legal_destinations_to_wire(cells: Iterable[Position]) -> List[List[int]]:
    return [position_to_wire(cell) for cell in cells]


def legal_destinations_from_wire(value: List[List[int]]) -> Set[Position]:
    return {position_from_wire(cell) for cell in value}

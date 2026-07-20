from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from kungfu_chess.engine.board_view_state import BoardViewState, MoveLogEntry, PieceView
from kungfu_chess.model.position import Position
from kungfu_chess.server import protocol
from kungfu_chess.server.messages import (
    JumpMessage,
    LoginFailedMessage,
    LoginMessage,
    LoginOkMessage,
    MatchFoundMessage,
    NoOpponentFoundMessage,
    OpponentDisconnectedMessage,
    OpponentReconnectedMessage,
    RestartMessage,
    SelectOrMoveMessage,
    StateMessage,
    WaitingForOpponentMessage,
)

"""Converts the DTOs in engine/board_view_state.py, and the message
envelopes in server/messages.py, to/from plain JSON-serializable dicts -
so a client (which never imports engine/model directly) can reconstruct
the exact same typed dataclasses Renderer.draw() already expects. No
parallel wire representation to keep in sync, and no json/dict literals
scattered through matchmaker.py/game_room.py/network_client_view.py -
they only ever build/read the typed message dataclasses; this module is
the only place that knows what the JSON actually looks like."""


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


def message_to_wire(message: Any) -> Dict[str, Any]:
    if isinstance(message, (WaitingForOpponentMessage, NoOpponentFoundMessage, RestartMessage, OpponentReconnectedMessage)):
        return {"type": message.type}
    if isinstance(message, LoginMessage):
        return {"type": message.type, "username": message.username, "password": message.password}
    if isinstance(message, LoginOkMessage):
        return {"type": message.type, "rating": message.rating}
    if isinstance(message, LoginFailedMessage):
        return {"type": message.type, "reason": message.reason}
    if isinstance(message, OpponentDisconnectedMessage):
        return {"type": message.type, "grace_seconds": message.grace_seconds}
    if isinstance(message, MatchFoundMessage):
        return {
            "type": message.type,
            "color": message.color,
            "white_username": message.white_username,
            "white_rating": message.white_rating,
            "black_username": message.black_username,
            "black_rating": message.black_rating,
        }
    if isinstance(message, StateMessage):
        return {
            "type": message.type,
            "board": board_view_state_to_wire(message.board),
            "your_selected_pos": position_to_wire(message.your_selected_pos),
            "your_legal_destinations": legal_destinations_to_wire(message.your_legal_destinations),
            "your_invalid_target": position_to_wire(message.your_invalid_target),
        }
    if isinstance(message, (SelectOrMoveMessage, JumpMessage)):
        return {"type": message.type, "row": message.row, "col": message.col}
    raise TypeError(f"don't know how to serialize {message!r}")


def message_from_wire(data: Dict[str, Any]) -> Any:
    message_type = data["type"]
    if message_type == protocol.LOGIN:
        return LoginMessage(username=data["username"], password=data["password"])
    if message_type == protocol.LOGIN_OK:
        return LoginOkMessage(rating=data["rating"])
    if message_type == protocol.LOGIN_FAILED:
        return LoginFailedMessage(reason=data["reason"])
    if message_type == protocol.WAITING_FOR_OPPONENT:
        return WaitingForOpponentMessage()
    if message_type == protocol.NO_OPPONENT_FOUND:
        return NoOpponentFoundMessage()
    if message_type == protocol.OPPONENT_DISCONNECTED:
        return OpponentDisconnectedMessage(grace_seconds=data["grace_seconds"])
    if message_type == protocol.OPPONENT_RECONNECTED:
        return OpponentReconnectedMessage()
    if message_type == protocol.MATCH_FOUND:
        return MatchFoundMessage(
            color=data["color"],
            white_username=data["white_username"],
            white_rating=data["white_rating"],
            black_username=data["black_username"],
            black_rating=data["black_rating"],
        )
    if message_type == protocol.STATE:
        return StateMessage(
            board=board_view_state_from_wire(data["board"]),
            your_selected_pos=position_from_wire(data["your_selected_pos"]),
            your_legal_destinations=legal_destinations_from_wire(data["your_legal_destinations"]),
            your_invalid_target=position_from_wire(data["your_invalid_target"]),
        )
    if message_type == protocol.SELECT_OR_MOVE:
        return SelectOrMoveMessage(row=data["row"], col=data["col"])
    if message_type == protocol.JUMP:
        return JumpMessage(row=data["row"], col=data["col"])
    if message_type == protocol.RESTART:
        return RestartMessage()
    raise ValueError(f"unknown message type: {message_type!r}")


def serialize_message(message: Any) -> str:
    """The only place json.dumps is called for the wire protocol -
    matchmaker.py/game_room.py/network_client_view.py build/read typed
    message dataclasses only, never raw dicts or JSON strings."""
    return json.dumps(message_to_wire(message))


def deserialize_message(raw: str) -> Any:
    return message_from_wire(json.loads(raw))

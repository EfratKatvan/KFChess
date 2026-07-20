from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Set

from kungfu_chess.engine.board_view_state import BoardViewState
from kungfu_chess.model.position import Position
from kungfu_chess.server import protocol

"""Typed envelopes for the client<->server WebSocket protocol - the same
"dataclass for the shape, a separate step for the wire format" split
engine/board_view_state.py already uses for BoardViewState. See
server/serialization.py for the to/from-wire conversion, and
protocol.py for the raw "type" string constants referenced below."""


@dataclass(frozen=True)
class LoginMessage:
    username: str
    password: str
    type: str = protocol.LOGIN


@dataclass(frozen=True)
class LoginOkMessage:
    rating: int
    type: str = protocol.LOGIN_OK


@dataclass(frozen=True)
class LoginFailedMessage:
    reason: str
    type: str = protocol.LOGIN_FAILED


@dataclass(frozen=True)
class WaitingForOpponentMessage:
    type: str = protocol.WAITING_FOR_OPPONENT


@dataclass(frozen=True)
class NoOpponentFoundMessage:
    type: str = protocol.NO_OPPONENT_FOUND


@dataclass(frozen=True)
class MatchFoundMessage:
    """Carries both players' identity, not just "your" color - the side
    panels display a username+rating per color (see renderer.py's
    PlayerInfo), and need White's info and Black's info regardless of
    which client is asking."""

    color: str
    white_username: str
    white_rating: int
    black_username: str
    black_rating: int
    type: str = protocol.MATCH_FOUND


@dataclass(frozen=True)
class StateMessage:
    board: BoardViewState
    your_selected_pos: Optional[Position]
    your_legal_destinations: Set[Position]
    your_invalid_target: Optional[Position]
    type: str = protocol.STATE


@dataclass(frozen=True)
class SelectOrMoveMessage:
    row: int
    col: int
    type: str = protocol.SELECT_OR_MOVE


@dataclass(frozen=True)
class JumpMessage:
    row: int
    col: int
    type: str = protocol.JUMP


@dataclass(frozen=True)
class RestartMessage:
    type: str = protocol.RESTART


@dataclass(frozen=True)
class OpponentDisconnectedMessage:
    """Sent once to the still-connected player - grace_seconds is how
    long the opponent has to reconnect (same username, see
    server/matchmaker.py) before auto-resigning. The client counts down
    locally from receipt, the same idiom as the match-start countdown -
    no need for the server to send a tick every second."""

    grace_seconds: int
    type: str = protocol.OPPONENT_DISCONNECTED


@dataclass(frozen=True)
class OpponentReconnectedMessage:
    type: str = protocol.OPPONENT_RECONNECTED

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Optional, Set

from kungfu_chess.engine.board_view_state import BoardViewState
from kungfu_chess.model.position import Position
from kungfu_chess.server.messages import (
    LoginFailedMessage,
    LoginOkMessage,
    MatchFoundMessage,
    NoOpponentFoundMessage,
    OpponentDisconnectedMessage,
    OpponentReconnectedMessage,
    StateMessage,
    WaitingForOpponentMessage,
)

"""The client's Model layer: what the client currently knows, and the
pure logic that updates it from an incoming server message. Nothing
here touches the network, a window, or drawing - see
client/network_transport.py (transport), client/input_controller.py
(turns clicks into outgoing messages), and view/network_presentation.py
(turns this state into pixels)."""


@dataclass(frozen=True)
class PlayerInfo:
    """Who's playing a given color, and their rating at match-start -
    identity, not game state, so it travels alongside ClientState
    rather than through BoardViewState."""

    username: str
    rating: int


@dataclass
class ClientState:
    """Everything the render loop needs to know about the match, as of
    the last message received - always replaced wholesale (see
    apply_message below), never mutated field by field, so a read from
    the main thread can't see a torn mix of an old view_state with a
    newer selected_pos."""

    phase: str = "connecting"  # connecting -> lobby -> waiting -> matched, or login_failed/no_opponent/disconnected
    color: Optional[str] = None
    rating: Optional[int] = None
    login_failure_reason: Optional[str] = None
    white_player: Optional[PlayerInfo] = None
    black_player: Optional[PlayerInfo] = None
    view_state: Optional[BoardViewState] = None
    selected_pos: Optional[Position] = None
    legal_destinations: Set[Position] = field(default_factory=set)
    invalid_target: Optional[Position] = None
    matched_at: Optional[float] = None
    game_over_started_at: Optional[float] = None
    opponent_disconnected_at: Optional[float] = None
    opponent_disconnect_grace_seconds: Optional[int] = None


def _game_over_started_at(previous: Optional[float], board_game_over: bool) -> Optional[float]:
    """Tracks the moment game_over first turned True (for the fade-in
    animation) - set once on the transition, cleared once a fresh game
    (restart) reports game_over False again."""
    if not board_game_over:
        return None
    return previous if previous is not None else time.perf_counter()


def apply_message(message: Any, state: ClientState) -> ClientState:
    """Pure state transition: given the previous state and one already-
    decoded server message, returns the new state - never mutates
    `state`, never touches I/O. client/network_transport.py is the only
    caller, and owns turning this into an actual ClientBox update."""
    if isinstance(message, LoginOkMessage):
        return ClientState(phase="lobby", rating=message.rating)  # waits here for the player to click Play
    if isinstance(message, LoginFailedMessage):
        return ClientState(phase="login_failed", login_failure_reason=message.reason)
    if isinstance(message, WaitingForOpponentMessage):
        return ClientState(phase="waiting", rating=state.rating)
    if isinstance(message, NoOpponentFoundMessage):
        return ClientState(phase="no_opponent", rating=state.rating)
    if isinstance(message, MatchFoundMessage):
        return ClientState(
            phase="matched", color=message.color, matched_at=time.perf_counter(),
            white_player=PlayerInfo(username=message.white_username, rating=message.white_rating),
            black_player=PlayerInfo(username=message.black_username, rating=message.black_rating),
        )
    if isinstance(message, OpponentDisconnectedMessage):
        return replace(
            state,
            opponent_disconnected_at=time.perf_counter(),
            opponent_disconnect_grace_seconds=message.grace_seconds,
        )
    if isinstance(message, OpponentReconnectedMessage):
        return replace(state, opponent_disconnected_at=None, opponent_disconnect_grace_seconds=None)
    if isinstance(message, StateMessage):
        return ClientState(
            phase="matched",
            color=state.color,
            view_state=message.board,
            selected_pos=message.your_selected_pos,
            legal_destinations=message.your_legal_destinations,
            invalid_target=message.your_invalid_target,
            matched_at=state.matched_at,
            game_over_started_at=_game_over_started_at(state.game_over_started_at, message.board.game_over),
            opponent_disconnected_at=state.opponent_disconnected_at,
            opponent_disconnect_grace_seconds=state.opponent_disconnect_grace_seconds,
            white_player=state.white_player,
            black_player=state.black_player,
        )
    return state  # unrecognized message type - state is unaffected

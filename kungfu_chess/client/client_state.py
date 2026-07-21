from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Optional, Set

from kungfu_chess.engine.board_view_state import BoardViewState
from kungfu_chess.model.position import Position
from kungfu_chess.server.messages import (
    CreateRoomFailedMessage,
    JoinRoomFailedMessage,
    LoginFailedMessage,
    LoginOkMessage,
    MatchFoundMessage,
    NoOpponentFoundMessage,
    OpponentDisconnectedMessage,
    OpponentReconnectedMessage,
    RoomCancelledMessage,
    RoomCreatedMessage,
    SpectatingMessage,
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

    # connecting -> lobby -> waiting/room_create_entry/room_join_entry ->
    # room_pending_ack -> room_waiting/matched/spectating, or
    # login_failed/no_opponent/room_action_failed/disconnected
    phase: str = "connecting"
    color: Optional[str] = None  # None while spectating - a spectator plays no side
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
    room_id: Optional[str] = None  # set once a room is created/joined/matched via it; None for a Play-matched game
    text_entry_value: str = ""  # the in-progress room name typed on the room_create_entry/room_join_entry screen
    pending_room_action: Optional[str] = None  # "create"/"join" - set while phase == "room_pending_ack"
    room_action_failure_reason: Optional[str] = None  # a RoomError's str(), from Create or Join failing
    room_action_failure_kind: Optional[str] = None  # "create"/"join" - which action failed, for the message text


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
            room_id=message.room_id,
        )
    if isinstance(message, RoomCreatedMessage):
        return ClientState(phase="room_waiting", rating=state.rating, room_id=message.room_id)
    if isinstance(message, JoinRoomFailedMessage):
        return ClientState(
            phase="room_action_failed", rating=state.rating,
            room_action_failure_reason=message.reason, room_action_failure_kind="join",
        )
    if isinstance(message, CreateRoomFailedMessage):
        return ClientState(
            phase="room_action_failed", rating=state.rating,
            room_action_failure_reason=message.reason, room_action_failure_kind="create",
        )
    if isinstance(message, RoomCancelledMessage):
        return ClientState(phase="lobby", rating=state.rating)
    if isinstance(message, SpectatingMessage):
        # matched_at is deliberately left None - a spectator isn't about
        # to move anything, so skip the "starting in N..." countdown a
        # real player gets and show the live board the instant it arrives
        # (see GameRoom.add_spectator's immediate snapshot).
        return ClientState(
            phase="spectating", color=None, room_id=message.room_id,
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
            # state.phase, not a hardcoded "matched" - a spectator's phase
            # ("spectating") must survive every tick's StateMessage, or
            # decide_message would start treating their clicks as move
            # attempts the moment the phase silently flipped back.
            phase=state.phase,
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
            room_id=state.room_id,  # must be carried forward, or it resets to None on the very next tick
        )
    return state  # unrecognized message type - state is unaffected

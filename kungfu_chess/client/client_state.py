from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, FrozenSet, Optional, Set, Type

from kungfu_chess.engine.board_view_state import BoardViewState
from kungfu_chess.model.position import Position
from kungfu_chess.server.messages import (
    CreateRoomFailedMessage,
    JoinRoomFailedMessage,
    LeftRoomMessage,
    LoginFailedMessage,
    LoginOkMessage,
    MatchFoundMessage,
    NoOpponentFoundMessage,
    OpponentDisconnectedMessage,
    OpponentReconnectedMessage,
    RoomCancelledMessage,
    RoomCreatedMessage,
    SeekCancelledMessage,
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


def _on_login_ok(message: LoginOkMessage, state: ClientState) -> ClientState:
    return ClientState(phase="lobby", rating=message.rating)  # waits here for the player to click Play


def _on_login_failed(message: LoginFailedMessage, state: ClientState) -> ClientState:
    return ClientState(phase="login_failed", login_failure_reason=message.reason)


def _on_waiting_for_opponent(message: WaitingForOpponentMessage, state: ClientState) -> ClientState:
    return ClientState(phase="waiting", rating=state.rating)


def _on_no_opponent_found(message: NoOpponentFoundMessage, state: ClientState) -> ClientState:
    return ClientState(phase="no_opponent", rating=state.rating)


def _on_match_found(message: MatchFoundMessage, state: ClientState) -> ClientState:
    return ClientState(
        phase="matched", color=message.color, matched_at=time.perf_counter(), rating=state.rating,
        white_player=PlayerInfo(username=message.white_username, rating=message.white_rating),
        black_player=PlayerInfo(username=message.black_username, rating=message.black_rating),
        room_id=message.room_id,
    )


def _on_room_created(message: RoomCreatedMessage, state: ClientState) -> ClientState:
    return ClientState(phase="room_waiting", rating=state.rating, room_id=message.room_id)


def _on_join_room_failed(message: JoinRoomFailedMessage, state: ClientState) -> ClientState:
    return ClientState(
        phase="room_action_failed", rating=state.rating,
        room_action_failure_reason=message.reason, room_action_failure_kind="join",
    )


def _on_create_room_failed(message: CreateRoomFailedMessage, state: ClientState) -> ClientState:
    return ClientState(
        phase="room_action_failed", rating=state.rating,
        room_action_failure_reason=message.reason, room_action_failure_kind="create",
    )


def _on_room_cancelled(message: RoomCancelledMessage, state: ClientState) -> ClientState:
    return ClientState(phase="lobby", rating=state.rating)


def _on_seek_cancelled(message: SeekCancelledMessage, state: ClientState) -> ClientState:
    return ClientState(phase="lobby", rating=state.rating)


def _on_left_room(message: LeftRoomMessage, state: ClientState) -> ClientState:
    return ClientState(phase="lobby", rating=state.rating)


def _on_spectating(message: SpectatingMessage, state: ClientState) -> ClientState:
    # matched_at is deliberately left None - a spectator isn't about
    # to move anything, so skip the "starting in N..." countdown a
    # real player gets and show the live board the instant it arrives
    # (see GameRoom.add_spectator's immediate snapshot).
    return ClientState(
        phase="spectating", color=None, room_id=message.room_id,
        white_player=PlayerInfo(username=message.white_username, rating=message.white_rating),
        black_player=PlayerInfo(username=message.black_username, rating=message.black_rating),
    )


def _on_opponent_disconnected(message: OpponentDisconnectedMessage, state: ClientState) -> ClientState:
    return replace(
        state,
        opponent_disconnected_at=time.perf_counter(),
        opponent_disconnect_grace_seconds=message.grace_seconds,
    )


def _on_opponent_reconnected(message: OpponentReconnectedMessage, state: ClientState) -> ClientState:
    return replace(state, opponent_disconnected_at=None, opponent_disconnect_grace_seconds=None)


def _on_state(message: StateMessage, state: ClientState) -> ClientState:
    if state.phase not in ("matched", "spectating"):
        # A stray broadcast from a game this client has already left
        # behind (e.g. a Play-matched GameRoom's tick loop keeps
        # running - and keeps broadcasting to this same websocket -
        # even after LeaveRoomMessage, since only Matchmaker's own
        # bookkeeping was freed, not the room itself). Rebuilding
        # ClientState from just this message's fields would silently
        # wipe out whatever local-only state the current screen owns
        # (e.g. room_create_entry's typed-so-far text_entry_value,
        # which isn't part of StateMessage at all) every time one of
        # these arrives - so outside the two phases that actually show
        # a board, a StateMessage is simply stale and ignored.
        return state
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


_HANDLERS: Dict[Type[Any], Callable[[Any, ClientState], ClientState]] = {
    LoginOkMessage: _on_login_ok,
    LoginFailedMessage: _on_login_failed,
    WaitingForOpponentMessage: _on_waiting_for_opponent,
    NoOpponentFoundMessage: _on_no_opponent_found,
    MatchFoundMessage: _on_match_found,
    RoomCreatedMessage: _on_room_created,
    JoinRoomFailedMessage: _on_join_room_failed,
    CreateRoomFailedMessage: _on_create_room_failed,
    RoomCancelledMessage: _on_room_cancelled,
    SeekCancelledMessage: _on_seek_cancelled,
    LeftRoomMessage: _on_left_room,
    SpectatingMessage: _on_spectating,
    OpponentDisconnectedMessage: _on_opponent_disconnected,
    OpponentReconnectedMessage: _on_opponent_reconnected,
    StateMessage: _on_state,
}


def apply_message(message: Any, state: ClientState) -> ClientState:
    """Pure state transition: given the previous state and one already-
    decoded server message, returns the new state - never mutates
    `state`, never touches I/O. client/network_transport.py is the only
    caller, and owns turning this into an actual ClientBox update - from
    there, view/network_client_view.py's render loop reads box.state
    every frame to draw it and to decide what a click/keypress means.
    Dispatches by exact message type through _HANDLERS, one function per
    message kind, instead of a growing if/elif chain."""
    handler = _HANDLERS.get(type(message))
    if handler is None:
        return state  # unrecognized message type - state is unaffected
    return handler(message, state)


# Sound-effect event tags - what events_since below detects, and what
# client/sound.py knows how to play. Defined here (not in sound.py) so
# this stays the single source of truth for "what counts as an event",
# the same way protocol.py is for wire message types.
GAME_START_EVENT = "game_start"
MOVE_EVENT = "move"
CAPTURE_EVENT = "capture"
GAME_OVER_EVENT = "game_over"


def events_since(old_state: ClientState, new_state: ClientState) -> FrozenSet[str]:
    """Pure diff between two consecutive states - what a sound layer
    (client/sound.py) should react to, without this module ever playing
    anything itself. Only looks at what actually changed, so it fires
    exactly once per event, however often a re-broadcast StateMessage
    repeats the same board.

    Move/capture entries are skipped whenever old_state has no
    view_state yet (right after match-found or a reconnect) - otherwise
    the first snapshot of an already-in-progress move log would replay
    every past move/capture as one burst of beeps."""
    events = set()
    if new_state.matched_at is not None and new_state.matched_at != old_state.matched_at:
        events.add(GAME_START_EVENT)

    if new_state.view_state is not None and old_state.view_state is not None:
        for color, entries in new_state.view_state.move_log.items():
            already_seen = len(old_state.view_state.move_log.get(color, ()))
            for entry in entries[already_seen:]:
                events.add(CAPTURE_EVENT if entry.is_capture else MOVE_EVENT)
        if new_state.view_state.game_over and not old_state.view_state.game_over:
            events.add(GAME_OVER_EVENT)

    return frozenset(events)

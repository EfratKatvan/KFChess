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
    """Only succeeds for an already-registered username (see
    accounts.login) - a client sends this from the shell's "Login"
    choice. Same shape as RegisterMessage; the `type` discriminator is
    what tells the server which rule to apply."""

    username: str
    password: str
    type: str = protocol.LOGIN


@dataclass(frozen=True)
class RegisterMessage:
    """The shell's "Register" choice - only succeeds for a username
    that doesn't exist yet (see accounts.register). Reuses
    LoginOkMessage/LoginFailedMessage for the response, same as
    LoginMessage does; only the request needs its own type, so the
    server knows not to fall back to an existing account."""

    username: str
    password: str
    type: str = protocol.REGISTER


@dataclass(frozen=True)
class LoginOkMessage:
    rating: int
    type: str = protocol.LOGIN_OK


@dataclass(frozen=True)
class LoginFailedMessage:
    reason: str
    type: str = protocol.LOGIN_FAILED


@dataclass(frozen=True)
class SeekGameMessage:
    """Sent when the player clicks "Play" in the lobby - the trigger
    that actually enters matchmaking (login by itself no longer does)."""

    type: str = protocol.SEEK_GAME


@dataclass(frozen=True)
class WaitingForOpponentMessage:
    type: str = protocol.WAITING_FOR_OPPONENT


@dataclass(frozen=True)
class CancelSeekMessage:
    """Sent when the player clicks Back on the "Waiting for
    opponent..." screen (see Matchmaker._start_seeking) - the Play
    button's counterpart to CancelRoomMessage."""

    type: str = protocol.CANCEL_SEEK


@dataclass(frozen=True)
class SeekCancelledMessage:
    """Acknowledges CancelSeekMessage and returns the client to the
    lobby - mirrors RoomCancelledMessage."""

    type: str = protocol.SEEK_CANCELLED


@dataclass(frozen=True)
class NoOpponentFoundMessage:
    type: str = protocol.NO_OPPONENT_FOUND


@dataclass(frozen=True)
class MatchFoundMessage:
    """Carries both players' identity, not just "your" color - the side
    panels display a username+rating per color (see renderer.py's
    PlayerInfo), and need White's info and Black's info regardless of
    which client is asking. room_id is None for an ELO-matched (Play
    button) game, and set for a game formed via the Room dialog - the
    client's top banner keeps showing it through gameplay either way
    (see network_presentation.py's _draw_top_banner)."""

    color: str
    white_username: str
    white_rating: int
    black_username: str
    black_rating: int
    room_id: Optional[str] = None
    type: str = protocol.MATCH_FOUND


@dataclass(frozen=True)
class StateMessage:
    board: BoardViewState
    your_selected_pos: Optional[Position]
    your_legal_destinations: Set[Position]
    your_invalid_target: Optional[Position]
    type: str = protocol.STATE


@dataclass(frozen=True)
class PieceMotionStartedMessage:
    """Sparse, unthrottled push sent the instant a move is accepted -
    Server_Design.md section 8. from_position doubles as the motion's
    id: a piece can't have two concurrent motions, so no piece has more
    than one pending motion keyed by its own starting cell at a time.
    The client already knows the piece's color/kind from the last full
    StateMessage at that position - only the timing/destination is new
    here."""

    from_position: Position
    to_position: Position
    duration_ms: int
    type: str = protocol.PIECE_MOTION_STARTED


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
class ResignMessage:
    """Sent when the player clicks Resign during a live match - forfeits
    immediately in the opponent's favor (see GameRoom.handle_message's
    resign handler), the same ELO/game-over path an auto-resign after a
    disconnect grace period already takes."""

    type: str = protocol.RESIGN


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


@dataclass(frozen=True)
class LeaveRoomMessage:
    """Sent when the player clicks "Back to Lobby" on the game-over
    overlay - only meaningful once the game has actually ended (see
    Matchmaker._leave_room); a no-op if it somehow arrives mid-game."""

    type: str = protocol.LEAVE_ROOM


@dataclass(frozen=True)
class LeftRoomMessage:
    """Acknowledges LeaveRoomMessage and returns the client to the
    lobby - mirrors RoomCancelledMessage/SeekCancelledMessage."""

    type: str = protocol.LEFT_ROOM


@dataclass(frozen=True)
class CreateRoomMessage:
    """Sent when the player types a room name and confirms on the
    "Create Room" text-entry screen."""

    room_id: str
    type: str = protocol.CREATE_ROOM


@dataclass(frozen=True)
class CreateRoomFailedMessage:
    reason: str  # a RoomError's str(), e.g. "room_name_taken" - see server/rooms.py
    type: str = protocol.CREATE_ROOM_FAILED


@dataclass(frozen=True)
class JoinRoomMessage:
    """Sent when the player picks "Join" with a room id typed into the
    dialog's text box."""

    room_id: str
    type: str = protocol.JOIN_ROOM


@dataclass(frozen=True)
class CancelRoomMessage:
    """Sent when the creator cancels a still-pending (no opponent yet)
    room - see RoomRegistry.cancel."""

    type: str = protocol.CANCEL_ROOM


@dataclass(frozen=True)
class RoomCreatedMessage:
    """Sent to the creator right after CreateRoomMessage - the "writes
    it on top of the screen" moment from the spec. The creator then
    waits (phase "room_waiting") until someone joins."""

    room_id: str
    type: str = protocol.ROOM_CREATED


@dataclass(frozen=True)
class JoinRoomFailedMessage:
    reason: str  # a RoomError's str(), e.g. "room_not_found" - see server/rooms.py
    type: str = protocol.JOIN_ROOM_FAILED


@dataclass(frozen=True)
class RoomCancelledMessage:
    """Acknowledges CancelRoomMessage - only ever sent to the creator,
    only while the room was still pending - returns them to the lobby."""

    type: str = protocol.ROOM_CANCELLED


@dataclass(frozen=True)
class SpectatingMessage:
    """The third+ joiner's counterpart to MatchFoundMessage - same
    player-identity payload, but no `color`, since a spectator has
    neither. Kept as its own message type rather than MatchFoundMessage
    with color=None, so client_state.py's dispatch and
    input_controller.py's phase-gating both get an unambiguous case
    instead of a nullable field every future branch has to remember to
    check."""

    room_id: str
    white_username: str
    white_rating: int
    black_username: str
    black_rating: int
    type: str = protocol.SPECTATING

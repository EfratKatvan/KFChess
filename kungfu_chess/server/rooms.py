from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Set

from kungfu_chess.server import protocol

"""Room bookkeeping for the lobby's Create/Join Room buttons - pure
logic, no websockets/asyncio, the same "pure decision, no I/O" split
client/input_controller.py's decide_message/apply_key_press already
use. server/matchmaker.py owns the actual connections and turns
"opponent seat just filled" into a real GameRoom; this module only
ever tracks which rooms exist, who's in them, and whether a joiner
becomes the opponent or a spectator."""


class RoomError(Exception):
    """str(error) is itself the wire-ready reason code (see
    server/messages.py's JoinRoomFailedMessage/CreateRoomFailedMessage
    reason) - the same role server/accounts.py's AuthResult.reason
    plays for a failed login."""


@dataclass
class Room:
    room_id: str  # the creator's typed name, exactly as they typed it (see RoomRegistry.create)
    creator_username: str
    opponent_username: Optional[str] = None
    spectator_usernames: Set[str] = field(default_factory=set)

    # A room stops being joinable as the opponent the instant a second
    # player fills it - every joiner after that is a spectator instead
    # (see RoomRegistry.join), and it's no longer cancellable (see
    # RoomRegistry.cancel), since a real game is what's now in progress.
    @property
    def is_pending(self) -> bool:
        return self.opponent_username is None


class RoomRegistry:
    """A username is creator/opponent/spectator of at most one room at
    a time - mirrors server/matchmaker.py's own "one live connection
    per username" rule. Room names are chosen by the player, not
    generated - looked up/deduplicated case-insensitively (so "Efrat-
    Room" and "efrat-room" are the same room), while the creator's
    exact typed casing is kept for display on Room.room_id."""

    def __init__(self) -> None:
        self._rooms: Dict[str, Room] = {}  # keyed by room_id.strip().upper()
        self._room_key_by_username: Dict[str, str] = {}  # username -> that same canonical key

    def create(self, username: str, room_id: str) -> Room:
        if username in self._room_key_by_username:
            raise RoomError("already_in_a_room")

        display_id = room_id.strip()
        if not display_id:
            raise RoomError("room_name_required")
        if len(display_id) > protocol.MAX_ROOM_ID_LENGTH:
            raise RoomError("room_name_too_long")
        key = display_id.upper()
        if key in self._rooms:
            raise RoomError("room_name_taken")

        room = Room(room_id=display_id, creator_username=username)
        self._rooms[key] = room
        self._room_key_by_username[username] = key
        return room

    # The first join fills the opponent seat; every join after that is
    # a spectator - never rejected, per the spec ("the following people
    # who join are viewers").
    def join(self, room_id: str, username: str) -> Room:
        room = self._rooms.get(room_id.strip().upper())
        if room is None:
            raise RoomError("room_not_found")
        if username in self._room_key_by_username:
            raise RoomError("already_in_a_room")

        if room.is_pending:
            room.opponent_username = username
        else:
            room.spectator_usernames.add(username)
        self._room_key_by_username[username] = room.room_id.upper()
        return room

    # Only the creator, and only before an opponent has joined - once a
    # room's game is running, leaving it is a disconnect/resignation
    # (see game_room.py's own disconnect-grace handling), not a
    # cancellation.
    def cancel(self, username: str) -> Room:
        room = self.room_for_username(username)
        if room is None:
            raise RoomError("not_in_a_room")
        if room.creator_username != username:
            raise RoomError("not_the_creator")
        if not room.is_pending:
            raise RoomError("already_started")

        self._forget(room)
        return room

    def room_for_username(self, username: str) -> Optional[Room]:
        key = self._room_key_by_username.get(username)
        return self._rooms.get(key) if key is not None else None

    # Called once the room's own game actually ends (see
    # GameRoom.on_game_over) - frees every member (creator, opponent,
    # every spectator) to create or join a new room, and drops the room
    # itself from the registry. A no-op if the room is already gone.
    def close(self, room_id: str) -> None:
        room = self._rooms.get(room_id.strip().upper())
        if room is not None:
            self._forget(room)

    def _forget(self, room: Room) -> None:
        key = room.room_id.upper()
        self._rooms.pop(key, None)
        self._room_key_by_username.pop(room.creator_username, None)
        if room.opponent_username is not None:
            self._room_key_by_username.pop(room.opponent_username, None)
        for spectator in room.spectator_usernames:
            self._room_key_by_username.pop(spectator, None)

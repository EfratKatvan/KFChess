from __future__ import annotations

from enum import Enum

"""ClientState.phase's closed set of values, and the room-action kind
(create/join) that travels alongside it - both purely client-local
(never serialized to/from the server), so they live here rather than
in server/protocol.py. `str` mixin so every existing dict lookup keyed
by phase (input_controller._CLICK_HANDLERS/_KEY_PRESS_HANDLERS,
network_presentation._PHASE_SCREENS) and every `phase="..."` call site
keeps working unchanged - members hash and compare equal to their
string value."""


class Phase(str, Enum):
    SKIN_MENU = "skin_menu"
    LOGIN_ENTRY = "login_entry"
    CONNECTING = "connecting"
    LOBBY = "lobby"
    WAITING = "waiting"
    NO_OPPONENT = "no_opponent"
    MATCHED = "matched"
    ROOM_WAITING = "room_waiting"
    ROOM_CREATE_ENTRY = "room_create_entry"
    ROOM_JOIN_ENTRY = "room_join_entry"
    ROOM_PENDING_ACK = "room_pending_ack"
    ROOM_ACTION_FAILED = "room_action_failed"
    SPECTATING = "spectating"
    DISCONNECTED = "disconnected"


class RoomAction(str, Enum):
    CREATE = "create"
    JOIN = "join"

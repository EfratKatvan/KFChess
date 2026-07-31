from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Union

"""Gateway<->Shard routing envelopes (Server_Design.md sections 2/3/15,
Stage 4a) - deliberately separate from server/protocol.py and
server/messages.py, which define the *client-facing* wire format.
These three messages are the one-time handshake a Gateway relay
connection sends the instant it opens, telling the Shard which room/
seat it's for; every message after that on the same connection is
ordinary client<->server traffic (already serialized via
server/serialization.py) simply relayed byte-for-byte, which the
Shard-hosted GameRoom never distinguishes from a real client
connection."""

HOST_SEAT = "host_seat"
RECONNECT = "reconnect"
SPECTATE = "spectate"


@dataclass(frozen=True)
class HostSeatMessage:
    """'Host this room, I'm bringing you the <color> seat' - sent once
    per seat of a brand-new room (an ELO match or a Room dialog game).
    The Shard pairs the two HostSeatMessages sharing a room_id before
    a GameRoom is ever constructed - see GameShard._handle_host_seat."""

    room_id: str
    color: str
    username: str
    opponent_username: str
    type: str = HOST_SEAT


@dataclass(frozen=True)
class ReconnectMessage:
    """'I'm username, reconnecting as color to room_id' - the Shard
    looks up its own live GameRoom and calls the existing
    GameRoom.try_reconnect; a missing room or an expired grace period
    is signaled only by the Shard closing this connection with nothing
    sent, which the Gateway treats identically to "back to the lobby"."""

    room_id: str
    color: str
    username: str
    type: str = RECONNECT


@dataclass(frozen=True)
class SpectateMessage:
    """'I'm username, watching room_id' - the Shard calls the existing
    GameRoom.add_spectator; a missing room closes the connection with
    nothing sent, same convention as ReconnectMessage."""

    room_id: str
    username: str
    type: str = SPECTATE


RoutingMessage = Union[HostSeatMessage, ReconnectMessage, SpectateMessage]


def serialize_routing(message: Any) -> Dict[str, Any]:
    if isinstance(message, HostSeatMessage):
        return {
            "type": message.type,
            "room_id": message.room_id,
            "color": message.color,
            "username": message.username,
            "opponent_username": message.opponent_username,
        }
    if isinstance(message, ReconnectMessage):
        return {"type": message.type, "room_id": message.room_id, "color": message.color, "username": message.username}
    if isinstance(message, SpectateMessage):
        return {"type": message.type, "room_id": message.room_id, "username": message.username}
    raise TypeError(f"don't know how to serialize {message!r}")


def deserialize_routing(data: Dict[str, Any]) -> Any:
    message_type = data["type"]
    if message_type == HOST_SEAT:
        return HostSeatMessage(
            room_id=data["room_id"], color=data["color"],
            username=data["username"], opponent_username=data["opponent_username"],
        )
    if message_type == RECONNECT:
        return ReconnectMessage(room_id=data["room_id"], color=data["color"], username=data["username"])
    if message_type == SPECTATE:
        return SpectateMessage(room_id=data["room_id"], username=data["username"])
    raise ValueError(f"unknown routing message type: {message_type!r}")


def send_routing_message(message: Any) -> str:
    """The single line of wire text a Gateway relay connection sends
    the Shard, once, the instant it opens - mirrors
    serialization.serialize_message's json.dumps choke-point, kept
    separate since this is a different (internal-only) wire format."""
    return json.dumps(serialize_routing(message))


def recv_routing_message(raw: str) -> Any:
    return deserialize_routing(json.loads(raw))

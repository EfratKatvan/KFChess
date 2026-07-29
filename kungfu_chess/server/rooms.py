from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Set

from redis.asyncio import Redis

from kungfu_chess.server import protocol

"""Room bookkeeping for the lobby's Create/Join Room buttons. Storage
lives in Redis (a Hash per room plus a Set of its spectators, and a
string per username pointing at their room's key) rather than an
in-process dict - the same move Stage 0 already made for the ELO
seeker queue (see matchmaker.py), and for the same reason
(Server_Design.md section 13): state keyed only by a live process's
own memory can never be split across worker processes later. The
*rules* themselves (who can create/join/cancel what, when a joiner
becomes the opponent vs. a spectator) are unchanged - only where they
read and write their bookkeeping from."""


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
    exact typed casing is kept for display on Room.room_id.

    namespace scopes every Redis key this registry touches - shared
    with the owning Matchmaker's seeker-queue namespace (see
    matchmaker.py's __init__), purely to keep separate Matchmaker
    instances (chiefly separate tests) from seeing each other's rooms
    on the one shared Redis server. Production only ever constructs
    one Matchmaker, so this is a test-isolation seam, not a
    production concern."""

    def __init__(self, redis_client: Redis, namespace: str) -> None:
        self._redis = redis_client
        self._namespace = namespace

    def _room_key(self, key: str) -> str:
        return f"room:{self._namespace}:{key}"

    def _spectators_key(self, key: str) -> str:
        return f"room:{self._namespace}:{key}:spectators"

    def _user_key(self, username: str) -> str:
        return f"room_by_user:{self._namespace}:{username}"

    async def create(self, username: str, room_id: str) -> Room:
        if await self._redis.exists(self._user_key(username)):
            raise RoomError("already_in_a_room")

        display_id = room_id.strip()
        if not display_id:
            raise RoomError("room_name_required")
        if len(display_id) > protocol.MAX_ROOM_ID_LENGTH:
            raise RoomError("room_name_too_long")
        key = display_id.upper()
        if await self._redis.exists(self._room_key(key)):
            raise RoomError("room_name_taken")

        await self._redis.hset(self._room_key(key), mapping={"room_id": display_id, "creator_username": username})
        await self._redis.set(self._user_key(username), key)
        return Room(room_id=display_id, creator_username=username)

    # The first join fills the opponent seat; every join after that is
    # a spectator - never rejected, per the spec ("the following people
    # who join are viewers").
    async def join(self, room_id: str, username: str) -> Room:
        key = room_id.strip().upper()
        room = await self._load(key)
        if room is None:
            raise RoomError("room_not_found")
        if await self._redis.exists(self._user_key(username)):
            raise RoomError("already_in_a_room")

        if room.is_pending:
            room.opponent_username = username
            await self._redis.hset(self._room_key(key), "opponent_username", username)
        else:
            room.spectator_usernames.add(username)
            await self._redis.sadd(self._spectators_key(key), username)
        await self._redis.set(self._user_key(username), key)
        return room

    # Only the creator, and only before an opponent has joined - once a
    # room's game is running, leaving it is a disconnect/resignation
    # (see game_room.py's own disconnect-grace handling), not a
    # cancellation.
    async def cancel(self, username: str) -> Room:
        room = await self.room_for_username(username)
        if room is None:
            raise RoomError("not_in_a_room")
        if room.creator_username != username:
            raise RoomError("not_the_creator")
        if not room.is_pending:
            raise RoomError("already_started")

        await self._forget(room)
        return room

    async def room_for_username(self, username: str) -> Optional[Room]:
        key = await self._redis.get(self._user_key(username))
        return await self._load(key) if key is not None else None

    # Called once the room's own game actually ends (see
    # GameRoom.on_game_over) - frees every member (creator, opponent,
    # every spectator) to create or join a new room, and drops the room
    # itself from the registry. A no-op if the room is already gone.
    async def close(self, room_id: str) -> None:
        room = await self._load(room_id.strip().upper())
        if room is not None:
            await self._forget(room)

    async def _load(self, key: str) -> Optional[Room]:
        data = await self._redis.hgetall(self._room_key(key))
        if not data:
            return None
        spectators = await self._redis.smembers(self._spectators_key(key))
        return Room(
            room_id=data["room_id"],
            creator_username=data["creator_username"],
            opponent_username=data.get("opponent_username"),
            spectator_usernames=set(spectators),
        )

    async def _forget(self, room: Room) -> None:
        key = room.room_id.upper()
        await self._redis.delete(self._room_key(key), self._spectators_key(key))
        usernames = [room.creator_username, *room.spectator_usernames]
        if room.opponent_username is not None:
            usernames.append(room.opponent_username)
        await self._redis.delete(*(self._user_key(u) for u in usernames))

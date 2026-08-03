from __future__ import annotations

from typing import Optional

from redis.asyncio import Redis

LEASE_TTL_MS = 5000  # Server_Design.md section 3's own example: SET room:<id>:owner <worker> NX PX 5000

# Atomic "renew, but only if I'm still the one holding it" - a plain
# GET-then-PEXPIRE isn't atomic, so a lease that expired a moment before
# this call could already have been legitimately re-acquired by a
# different worker by the time a non-atomic check would notice,
# silently extending a lease this caller no longer actually holds.
_RENEW_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("PEXPIRE", KEYS[1], ARGV[2])
else
    return 0
end
"""

"""Redis-backed `room_id -> shard_address` lease (Server_Design.md
section 3) - the literal `SET room:<id>:owner <worker-id> NX PX 5000`
the design doc itself specifies, made real: not just mutual exclusion
("only one worker may advance this room's simulation"), but a genuine
address a *different* process can resolve a room_id to, closing the
gap ws_gateway.py's own comment used to name explicitly (a single
fixed SHARD_HOST/SHARD_PORT, correct only because exactly one Game
Shard has ever existed).

Written by game_allocator.py (acquires on allocation, renews by
heartbeat while the room stays live, releases on game-over - see that
module for why the lease's own *value* is now this worker's advertised
address rather than an opaque id). Read by ws_gateway.py, to resolve
an *existing* room_id (a reconnect or a spectator join) to the shard
address currently holding it, instead of assuming it's always the same
one.

Deliberately not the placement decision itself: choosing which shard a
*brand-new* room should be built on (today, trivial - there is only
ever one Game Shard, `game-shard.yaml`'s own `replicas: 1`) is a
separate, not-yet-needed mechanism - a pool of candidate shards to
place onto, not a registry of where an already-placed room lives. This
class only ever answers "where does this room already live," never
"which worker should host a new one.\""""


class RoomShardRegistry:
    def __init__(self, redis_client: Redis, namespace: str = "") -> None:
        self._redis = redis_client
        self._namespace = namespace

    def key(self, room_id: str) -> str:
        return f"room:{self._namespace}:{room_id}:owner"

    async def acquire(self, room_id: str, shard_address: str, ttl_ms: int = LEASE_TTL_MS) -> bool:
        return bool(await self._redis.set(self.key(room_id), shard_address, nx=True, px=ttl_ms))

    async def renew(self, room_id: str, shard_address: str, ttl_ms: int = LEASE_TTL_MS) -> bool:
        result = await self._redis.eval(_RENEW_SCRIPT, 1, self.key(room_id), shard_address, ttl_ms)
        return bool(result)

    async def get(self, room_id: str) -> Optional[str]:
        return await self._redis.get(self.key(room_id))

    async def release(self, room_id: str) -> None:
        await self._redis.delete(self.key(room_id))

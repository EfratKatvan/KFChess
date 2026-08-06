from __future__ import annotations

from redis.asyncio import Redis

# Atomic "renew, but only if I'm still the one holding it" - a plain
# GET-then-PEXPIRE isn't atomic, so a lease that expired a moment before
# this call could already have been legitimately re-acquired by someone
# else by the time a non-atomic check would notice, silently extending
# a lease this caller no longer actually holds.
#
# Shared by every NX+PX lease in this codebase - room_shard_registry.py's
# room-ownership lease and matchmaker_leader.py's leader-election lease
# both used to carry their own byte-identical copy of this script. That
# duplication was never justified the way the two lease *classes*
# themselves are (see each module's own docstring: they protect
# genuinely different things with different lifecycles - one room vs.
# one Matchmaking Service deployment - which is why they stay separate
# classes, not one). The atomic primitive underneath is the same
# operation either way, so it lives here once.
_RENEW_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("PEXPIRE", KEYS[1], ARGV[2])
else
    return 0
end
"""


async def renew_if_owner(redis_client: Redis, key: str, owner: str, ttl_ms: int) -> bool:
    """True if `owner` still held `key` and its TTL was extended; False
    if someone else holds it now (already-lapsed-and-reclaimed) or
    never did."""
    result = await redis_client.eval(_RENEW_SCRIPT, 1, key, owner, ttl_ms)
    return bool(result)

from __future__ import annotations

import uuid

from redis.asyncio import Redis

from kungfu_chess.server.redis_lease import renew_if_owner

LEADER_TTL_MS = 3000  # renewed well inside this - see matchmaking_service.py's own tick loop
# Also the matching-sweep cadence, not just the lease renewal cadence -
# matchmaking_service.py's tick loop calls try_become_leader() and the
# actual pairing sweep together, once per tick (matchmaker.py's own
# run_matching_tick). A player's "Play" click is only ever acted on at
# the next tick, so this interval is really the seek-to-match latency
# budget, not just a failover-safety margin - 0.2s keeps that
# imperceptible while still renewing the 3s lease with a wide (15x)
# safety margin.
LEADER_RENEWAL_SECONDS = 0.2

"""Leader election for the standalone Matchmaking Service
(matchmaking_service.py) - the fix for the race matchmaker.py's own
module docstring used to describe: the seekers queue (section 16.1's
Redis ZSET) is genuinely shared across replicas, but *deciding* who
pairs with whom, and *notifying* them, must only ever happen once per
match - not once per replica that happens to be looking at the queue
at the same moment. Every replica still accepts SeekGameMessage/
CancelSeekMessage directly (enqueue/dequeue have no shared counter to
race on - see matchmaker.py's _start_seeking/_cancel_seeking) - only
whichever replica currently holds this lease actually runs the
periodic matching sweep (matchmaker.py's run_matching_tick).

A plain NX+PX acquire-or-renew lease, the same shape
room_shard_registry.py's own room-ownership lease already uses - "only
one holder at a time, self-healing on crash via TTL expiry" is exactly
the same property both need, just applied to "who runs the matching
sweep" instead of "which worker owns this room." Kept as its own
module rather than folded into that one: they're leases over two
genuinely different things with different lifecycles (one per
Matchmaking Service deployment, not one per room), not the same
concept twice."""


class MatchmakerLeaderElection:
    def __init__(self, redis_client: Redis, namespace: str = "", instance_id: str = None) -> None:
        self._redis = redis_client
        self._key = f"matchmaker_leader:{namespace}"
        self._instance_id = instance_id or uuid.uuid4().hex
        self._is_leader = False

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    async def try_become_leader(self) -> bool:
        """Called on every tick (matchmaking_service.py's own loop) -
        acquires the lease if no one currently holds it, or renews it
        if this instance already does. Returns (and caches in
        is_leader) whether this instance is the leader as of right
        now."""
        acquired = await self._redis.set(self._key, self._instance_id, nx=True, px=LEADER_TTL_MS)
        if acquired:
            self._is_leader = True
            return True
        renewed = await renew_if_owner(self._redis, self._key, self._instance_id, LEADER_TTL_MS)
        self._is_leader = renewed
        return self._is_leader

    async def resign(self) -> None:
        """Best-effort - lets a *different* replica take over
        immediately on a clean shutdown, rather than waiting out the
        full TTL. Never required for correctness (a crashed leader's
        lease simply expires on its own), only for a faster handover
        on an ordinary, deliberate stop."""
        if self._is_leader:
            await self._redis.delete(self._key)
            self._is_leader = False

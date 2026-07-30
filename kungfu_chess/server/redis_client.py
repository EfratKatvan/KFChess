from __future__ import annotations

import redis.asyncio as redis

"""Thin wrapper around redis.asyncio - the rest of the server talks to
Redis only through get_client(), never redis-py directly, mirroring
the same "pure logic, thin adapter" split accounts.py already keeps
between its own logic and its storage (see Server_Design.md section
13.2). Keeps the storage backend a single, swappable seam - the point
Server_Design.md's Stage 0 (section 19) is actually about."""

REDIS_HOST = "localhost"
REDIS_PORT = 6379


def get_client(host: str = REDIS_HOST, port: int = REDIS_PORT) -> redis.Redis:
    """A new Redis client, connection-pooled internally by redis-py.
    Deliberately not cached as a process-wide singleton: a
    redis.asyncio.Redis instance's connections are bound to the event
    loop that created them, and this server's tests each run their own
    asyncio.run() (its own fresh event loop) - a cached client created
    under one test's loop would break on the next. Production only
    ever calls this once anyway (Matchmaker is constructed a single
    time in ws_gateway.py's run()), so there's no real cost either way."""
    return redis.Redis(host=host, port=port, decode_responses=True)

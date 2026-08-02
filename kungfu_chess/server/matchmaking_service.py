from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, Optional

from aiohttp import web
from redis.asyncio import Redis

from kungfu_chess.logging_config import configure_logging
from kungfu_chess.server import shard_protocol
from kungfu_chess.server.accounts_client import AccountsClient
from kungfu_chess.server.accounts_client import get_client as get_accounts_client
from kungfu_chess.server.auth_token import TokenClaims
from kungfu_chess.server.matchmaker import Matchmaker
from kungfu_chess.server.redis_client import get_client as get_redis_client

# Env-overridable (Stage 5, section 17), same pattern as every other role.
HOST = os.environ.get("HOST", "localhost")
PORT = int(os.environ.get("PORT", "8768"))
LOG_FILE = "matchmaking_service.log"

"""The Matchmaking Service (Server_Design.md section 1's "Matchmaker
service" row, section 14 row 3): the network-reachable home for
Matchmaker's fairness logic - the piece that was still missing after
Stage 4a, since `matchmaker.py` itself never had a transport of its
own (see Server_Design.md section 19's Stage 5 note, and this stage's
own entry below it). `Matchmaker`'s actual logic is untouched by this
- it already only ever calls `.send()`/`.close()` on whatever
connection-like object it's given (proven by test_matchmaker.py's own
`FakeConnection`), so `_RemoteConnection` below is simply a second
implementation of that same informal port, alongside the real
`ServerConnection` ws_gateway.py used to hand it directly when they
shared one process.

Transport (Server_Design.md section 16.2): HTTP for anything that is a
direct reply to the call that triggered it (accept/reject a connect, an
immediate CREATE_ROOM_FAILED, etc.) - and Redis Pub/Sub, not NATS, for
the two things that are NOT a direct reply to the caller's own request:
signaling a match/room-seat to the *other* player (found by a call this
connection never made) and the seek-timeout's NO_OPPONENT_FOUND (fired
by an internal timer, no request to reply to at all). NATS is
deliberately not used yet - it would add new infra for zero durability
payoff before JetStream/crash-recovery (section 3) is actually built;
Redis is already deployed everywhere else in this stack."""


class _RemoteConnection:
    """Matchmaker's `ws` port, implemented over the network instead of a
    live socket (Stage 4a's game_shard.py needed no such thing - a Shard
    is *reached by* the Gateway's own relay socket; a Matchmaking
    Service instead has to *reach back into* whichever Gateway holds the
    real client, hence Pub/Sub). One instance per connection_id, cached
    for the connection's whole lobby lifetime by whoever owns it (see
    create_app's _connections dict) so repeated calls resolve to the
    same object - Matchmaker's own `_username_of` relies on dict-key
    identity (`connection is ws`), exactly as it already does for a
    real ServerConnection."""

    def __init__(self, connection_id: str, redis_client: Redis) -> None:
        self.connection_id = connection_id
        self._redis = redis_client

    async def send(self, raw: str) -> None:
        await self._redis.publish(f"mm:{self.connection_id}", json.dumps({"kind": "reply", "raw": raw}))

    async def close(self) -> None:
        await self._redis.publish(f"mm:{self.connection_id}", json.dumps({"kind": "close"}))


def _claims_from_json(data: Optional[Dict[str, Any]]) -> Optional[TokenClaims]:
    if data is None:
        return None
    return TokenClaims(username=data["username"], rating=data["rating"], jti=data["jti"], expires_at=data["expires_at"])


def create_app(
    accounts_client: Optional[AccountsClient] = None,
    redis_client: Optional[Redis] = None,
    namespace: str = "",
) -> web.Application:
    """Per-app state, not module globals (mirrors accounts_service.py's
    own create_app(db_path) reasoning) - tests start several of these
    concurrently, each its own isolated namespace, and module-level
    dicts would leak connections between them.

    Building the default AccountsClient (an aiohttp.ClientSession under
    the hood) has to wait for on_startup, not happen here - create_app
    itself runs synchronously, before web.run_app has started the event
    loop that owns it. accounts_service.py never hit this because it's
    only ever an HTTP *server*; this is the first role that also has to
    be an HTTP *client* of another service, a combination this codebase
    hadn't exercised before. A caller that already has a client/redis
    instance (every test) is unaffected - only main()'s empty defaults
    are deferred."""
    redis_client = redis_client or get_redis_client()  # redis.asyncio.Redis() itself needs no running loop
    connections: Dict[str, _RemoteConnection] = {}
    state: Dict[str, Any] = {"matchmaker": None}

    def _on_enter_relay(connection: _RemoteConnection, routing: shard_protocol.RoutingMessage) -> None:
        # Fired, never awaited - matches matchmaker.py's own documented
        # contract for this callback. Scheduled as a background task so
        # the synchronous call inside Matchmaker returns immediately.
        payload = json.dumps({"kind": "routing", "routing": shard_protocol.serialize_routing(routing)})
        asyncio.create_task(redis_client.publish(f"mm:{connection.connection_id}", payload))

    async def _on_startup(app: web.Application) -> None:
        state["matchmaker"] = Matchmaker(
            accounts_client=accounts_client or get_accounts_client(),
            redis_client=redis_client,
            on_enter_relay=_on_enter_relay,
            namespace=namespace,
        )

    def _connection_for(connection_id: str) -> _RemoteConnection:
        connection = connections.get(connection_id)
        if connection is None:
            connection = _RemoteConnection(connection_id, redis_client)
            connections[connection_id] = connection
        return connection

    async def connect(request: web.Request) -> web.Response:
        body = await request.json()
        connection = _connection_for(body["connection_id"])
        accepted = await state["matchmaker"].on_connect(
            connection, body["username"], _claims_from_json(body.get("claims"))
        )
        return web.json_response({"accepted": accepted})

    async def message(request: web.Request) -> web.Response:
        body = await request.json()
        connection = connections.get(body["connection_id"])
        if connection is not None:
            await state["matchmaker"].on_message(connection, body["raw"])
        return web.json_response({})

    async def leave_relay(request: web.Request) -> web.Response:
        body = await request.json()
        connection = connections.get(body["connection_id"])
        if connection is not None:
            await state["matchmaker"].on_leave_relay(connection)
        return web.json_response({})

    async def disconnect(request: web.Request) -> web.Response:
        body = await request.json()
        connection = connections.pop(body["connection_id"], None)
        if connection is not None:
            await state["matchmaker"].on_disconnect(connection)
        return web.json_response({})

    app = web.Application()
    app.on_startup.append(_on_startup)
    app.router.add_post("/connect", connect)
    app.router.add_post("/message", message)
    app.router.add_post("/leave_relay", leave_relay)
    app.router.add_post("/disconnect", disconnect)
    return app


def main() -> None:
    configure_logging(LOG_FILE)
    web.run_app(create_app(), host=HOST, port=PORT)


if __name__ == "__main__":
    main()

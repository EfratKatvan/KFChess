from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from typing import Any, Dict, Optional

from aiohttp import web
from redis.asyncio import Redis

from kungfu_chess.logging_config import configure_logging
from kungfu_chess.server import shard_protocol
from kungfu_chess.server.accounts_client import AccountsClient
from kungfu_chess.server.accounts_client import get_client as get_accounts_client
from kungfu_chess.server.agones_allocation_client import AgonesAllocationClient
from kungfu_chess.server.auth_token import TokenClaims
from kungfu_chess.server.matchmaker import Matchmaker
from kungfu_chess.server.matchmaker_leader import LEADER_RENEWAL_SECONDS, MatchmakerLeaderElection
from kungfu_chess.server.metrics import start_metrics_server
from kungfu_chess.server.redis_client import get_client as get_redis_client

# Env-overridable (Stage 5, section 17), same pattern as every other role.
HOST = os.environ.get("HOST", "localhost")
PORT = int(os.environ.get("PORT", "8768"))
LOG_FILE = "matchmaking_service.log"

# Server_Design.md section 3 (Stage 7): opt-in, off by default - every
# environment without an Agones-managed Fleet to allocate from
# (docker-compose, the whole test suite) must keep placing brand-new
# rooms exactly as it always did (whichever replica Kubernetes' own
# Service happens to route a HostSeatMessage to). Only
# k8s/matchmaking.yaml's own Deployment sets this to "true", alongside
# the ServiceAccount/RBAC that makes the underlying K8s API call
# actually authorized. AGONES_K8S_NAMESPACE is the Kubernetes
# namespace the GameServerAllocation call targets - a different concept
# from create_app's own `namespace` parameter (that one isolates this
# app's own Redis keys; this one is Kubernetes' own resource
# namespace) - deliberately not read from the pod's own
# serviceaccount/namespace file, to keep this explicit and match how
# every other role already names "kfchess" directly in its own manifest.
AGONES_ALLOCATION_ENABLED = os.environ.get("AGONES_ALLOCATION_ENABLED", "false").lower() == "true"
AGONES_K8S_NAMESPACE = os.environ.get("AGONES_K8S_NAMESPACE", "default")

logger = logging.getLogger(__name__)

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
    # asyncio.create_task() only keeps a *weak* reference to the task it
    # returns - a fire-and-forget task with nothing else holding a
    # reference to it can be garbage-collected before it ever actually
    # runs (this is documented asyncio behavior, not a bug in
    # create_task itself). _on_enter_relay's own publish used to do
    # exactly that, and under real concurrent load (many matches
    # decided in the same tick - see matchmaker.py's _sweep_matches)
    # this intermittently dropped the Redis publish entirely: a real
    # k8s deployment with matchmaking replicas=2 reproduced it directly
    # (one seeker out of several concurrent pairs would never receive
    # its MATCH_FOUND). Keeping every such task in this set until it
    # finishes is the standard fix.
    _background_tasks: set = set()

    def _on_enter_relay(connection_id: str, routing: shard_protocol.RoutingMessage) -> None:
        # Fired, never awaited - matches matchmaker.py's own documented
        # contract for this callback. Scheduled as a background task so
        # the synchronous call inside Matchmaker returns immediately.
        # connection_id is now a plain string (this stage's own change -
        # see matchmaker.py's own on_enter_relay docstring): a leader
        # replica publishing this is never required to have accepted
        # this connection itself - Redis Pub/Sub reaches the right
        # Gateway regardless of which Matchmaking Service replica
        # decided the match, closing the cross-replica notification gap
        # a purely in-memory `connections` dict would otherwise leave.
        payload = json.dumps({"kind": "routing", "routing": shard_protocol.serialize_routing(routing)})
        task = asyncio.create_task(redis_client.publish(f"mm:{connection_id}", payload))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    async def _on_startup(app: web.Application) -> None:
        state["leader_election"] = MatchmakerLeaderElection(redis_client, namespace=namespace)
        agones_allocator = AgonesAllocationClient(namespace=AGONES_K8S_NAMESPACE) if AGONES_ALLOCATION_ENABLED else None
        state["matchmaker"] = Matchmaker(
            accounts_client=accounts_client or get_accounts_client(),
            redis_client=redis_client,
            on_enter_relay=_on_enter_relay,
            namespace=namespace,
            leader_election=state["leader_election"],
            remote_connection_resolver=_connection_for,
            agones_allocator=agones_allocator,
        )
        state["tick_task"] = asyncio.create_task(_run_matching_tick_loop())

    async def _run_matching_tick_loop() -> None:
        # One tick loop per replica (Server_Design.md section 16.1) -
        # try_become_leader() below is what makes running this
        # everywhere safe: only whichever replica currently holds the
        # lease actually sweeps the queue on any given tick (see
        # matchmaker_leader.py). A replica that isn't leader still calls
        # run_matching_tick() every interval - it's a cheap no-op then,
        # and it's what lets a non-leader replica take over instantly
        # once the current leader's lease lapses.
        while True:
            await asyncio.sleep(LEADER_RENEWAL_SECONDS)
            try:
                await state["matchmaker"].run_matching_tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("matching tick failed")

    async def _on_cleanup(app: web.Application) -> None:
        tick_task = state.get("tick_task")
        if tick_task is not None:
            tick_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await tick_task
        leader_election = state.get("leader_election")
        if leader_election is not None:
            await leader_election.resign()

    def _connection_for(connection_id: str) -> _RemoteConnection:
        # Always resolves - never a lookup that can miss. _RemoteConnection
        # carries no state of its own (just connection_id + a Redis
        # client - see its own docstring), so any replica can construct
        # one for any connection_id on demand; `connections` is purely a
        # cache to avoid reallocating one per call, never a correctness
        # requirement. Getting this wrong here was a real, found bug: a
        # Kubernetes Service gives no session affinity, so /connect and a
        # later /message|/leave_relay|/disconnect for the same
        # connection_id can each land on a *different* replica - a plain
        # `connections.get(...)` (returning None, silently no-op'ing the
        # call while still answering 200 OK) on any of those three routes
        # meant a seek/leave/disconnect that happened to land on a
        # replica other than the one that handled /connect was silently
        # dropped: the seeker never got matched (nothing ever called
        # Matchmaker.on_message for it), and a dropped /disconnect left
        # that connection's Matchmaker-side state (active_by_username and
        # friends - see matchmaker.py's own __init__ note) stale forever.
        # Reproduced directly against a real 2-replica deployment.
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
        connection = _connection_for(body["connection_id"])
        await state["matchmaker"].on_message(connection, body["raw"])
        return web.json_response({})

    async def leave_relay(request: web.Request) -> web.Response:
        body = await request.json()
        connection = _connection_for(body["connection_id"])
        await state["matchmaker"].on_leave_relay(connection)
        return web.json_response({})

    async def disconnect(request: web.Request) -> web.Response:
        body = await request.json()
        connection = _connection_for(body["connection_id"])
        connections.pop(body["connection_id"], None)
        await state["matchmaker"].on_disconnect(connection)
        return web.json_response({})

    app = web.Application()
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    app.router.add_post("/connect", connect)
    app.router.add_post("/message", message)
    app.router.add_post("/leave_relay", leave_relay)
    app.router.add_post("/disconnect", disconnect)
    return app


def main() -> None:
    configure_logging(LOG_FILE)
    start_metrics_server()
    web.run_app(create_app(), host=HOST, port=PORT)


if __name__ == "__main__":
    main()

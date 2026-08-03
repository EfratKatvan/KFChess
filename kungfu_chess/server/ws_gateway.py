from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict, Optional, Tuple, Union

from prometheus_client import Gauge
from redis.asyncio import Redis
from websockets.asyncio.client import connect
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from kungfu_chess.logging_config import configure_logging
from kungfu_chess.server import accounts, auth_token, shard_protocol
from kungfu_chess.server.accounts_client import ACCOUNTS_SERVICE_URL, AccountsClient
from kungfu_chess.server.accounts_client import get_client as get_accounts_client
from kungfu_chess.server.auth_token import TokenClaims
from kungfu_chess.server.game_shard import SHARD_HOST, SHARD_PORT
from kungfu_chess.server.matchmaking_client import MATCHMAKING_SERVICE_URL, MatchmakingClient
from kungfu_chess.server.matchmaking_client import get_client as get_matchmaking_client
from kungfu_chess.server.messages import (
    LoginFailedMessage,
    LoginMessage,
    LoginOkMessage,
    RegisterMessage,
    TokenLoginMessage,
)
from kungfu_chess.server.metrics import start_metrics_server
from kungfu_chess.server.redis_client import get_client as get_redis_client
from kungfu_chess.server.room_shard_registry import RoomShardRegistry

# Server_Design.md section 1: this role's own named scaling metric is
# open connection count.
ACTIVE_CONNECTIONS = Gauge("ws_gateway_active_connections", "Currently open client WebSocket connections")
from kungfu_chess.server.serialization import deserialize_message, serialize_message

# Env-overridable (Stage 5, section 17): docker-compose binds this to
# 0.0.0.0 so the container accepts the real client's connection from
# outside - "localhost" remains the default for local runs.
HOST = os.environ.get("HOST", "localhost")
PORT = int(os.environ.get("PORT", "8765"))
LOG_FILE = "ws_gateway.log"

logger = logging.getLogger(__name__)

"""The WS Gateway (Server_Design.md section 1's "WS Gateway" row,
section 14 row 2, section 14.2): the live-connection entry point - it
accepts the socket, drives the login/register handshake (over HTTP to
the Accounts/Ratings API Service via AccountsClient, never sqlite3
directly), then forwards every subsequent raw lobby message to the
Matchmaking Service (matchmaking_service.py) over HTTP while the
connection is in "lobby mode" - a separate process since the stage
after this file's own note below, no longer sharing Matchmaker's
memory directly. Whatever the Matchmaking Service needs to push back -
an ordinary reply, a match/room/reconnect/spectate routing signal, or a
forced close (Stage 1b's Logout) - arrives over a Redis Pub/Sub channel
scoped to this one connection (see _drain_pubsub), the same role
`relay_queues` played back when Matchmaker lived in this same process.
Stage 4a (section 19): a routing signal makes this module open its own
outbound connection to the Game Shard and switch into "relay mode" -
pumping raw bytes both directions between the real client socket and
the Shard - until the Shard ends that session, at which point the
connection goes back to lobby mode. No game or matchmaking logic lives
here, only transport/protocol/routing."""


async def _drain_pubsub(pubsub: Any, queue: "asyncio.Queue[Dict[str, Any]]") -> None:
    """Runs for a connection's whole lobby lifetime (across any number
    of lobby<->relay switches, same as `relay_queues` used to): reads
    everything the Matchmaking Service publishes on this connection's
    channel and funnels it into a local queue, so the rest of this
    module can keep racing "the client's next message" against "the
    Matchmaking Service's next push" exactly the way it already did
    when that push came from an in-process callback instead of the
    network (see _handle_connection)."""
    async for message in pubsub.listen():
        if message["type"] != "message":
            continue  # the subscribe-confirmation message, not a real push
        queue.put_nowait(json.loads(message["data"]))


async def _try_send(ws: ServerConnection, message: Any) -> None:
    """Transport: best-effort send - a closed/closing socket shouldn't
    blow up the caller, but the failure is still worth a log line
    instead of vanishing silently."""
    try:
        await ws.send(serialize_message(message))
    except Exception as error:
        logger.debug("send failed on %s: %s", ws.remote_address, error)


async def _recv_login_message(ws: ServerConnection) -> Optional[Union[LoginMessage, RegisterMessage, TokenLoginMessage]]:
    """Transport + protocol: reads exactly one message off the wire and
    checks it's a login/register/token-login request (see
    network_client_view.py's shell username/password prompt - or, since
    Stage 1b, its "Continue as X" saved-session button - sent right
    after connecting). Returns None - logging why - for anything that
    isn't: a socket that closed before sending anything, a malformed
    payload, or a message of the wrong type sent before login
    completed. No model or presentation logic lives here."""
    try:
        raw = await ws.recv()
    except Exception as error:
        logger.info("connection closed before login: %s", error)
        return None

    try:
        message = deserialize_message(raw)
    except (ValueError, KeyError, TypeError) as error:
        logger.warning("malformed login attempt: %s", error)
        return None

    if not isinstance(message, (LoginMessage, RegisterMessage, TokenLoginMessage)):
        logger.warning("expected a login, register, or token-login message first, got %s", type(message).__name__)
        return None
    return message


def _login_response(result: accounts.AuthResult, username: str) -> Any:
    """Presentation: turns the model's AuthResult into the wire message
    the client understands - pure, no I/O, no knowledge of sockets.
    Shared by both login and register, since a successful register
    leaves the player logged in the same way a successful login does.
    `username` is passed separately since AuthResult itself carries no
    identity - only what the DB knew (rating, a fresh token, or a
    failure reason)."""
    if not result.success:
        return LoginFailedMessage(reason=result.reason or "login failed")
    return LoginOkMessage(rating=result.rating, username=username, token=result.token)


async def _authenticate(
    ws: ServerConnection, accounts_client: AccountsClient, redis_client: Redis
) -> Optional[Tuple[str, int, TokenClaims]]:
    """Application: orchestrates one login/register/token-login by
    calling each layer in turn - transport/protocol
    (_recv_login_message), model (accounts_client.login/register - an
    HTTP call to the Accounts/Ratings API Service, never sqlite3
    directly, per Server_Design.md section 6 - or, for a
    TokenLoginMessage, local JWT verification plus a Redis revocation
    check, section 1.1's whole point: no network call to Accounts
    needed to re-prove an already-proven identity), presentation
    (_login_response), then transport again (_try_send) - without any
    layer's logic living inside another. Returns the authenticated
    (username, rating, token claims), or None if the connection should
    be dropped (bad credentials, an invalid/expired/revoked token, or
    anything else went wrong before login completed)."""
    message = await _recv_login_message(ws)
    if message is None:
        return None

    if isinstance(message, TokenLoginMessage):
        claims = auth_token.verify_token(message.token)
        if claims is None:
            await _try_send(ws, LoginFailedMessage(reason="invalid or expired session"))
            return None
        if await redis_client.exists(f"revoked:token:{claims.jti}"):
            await _try_send(ws, LoginFailedMessage(reason="session was logged out"))
            return None
        # Identity comes only from the verified token's own claims,
        # never from message.username (that field exists purely for
        # display/logging - see TokenLoginMessage's docstring). Rating
        # is re-fetched fresh rather than trusting the claim, which can
        # be stale the instant a game finishes after the token was
        # issued - the same reasoning matchmaker.py's _start_seeking
        # already applies to every other login path.
        rating = await accounts_client.get_rating(claims.username)
        if rating is None:
            rating = claims.rating
        await _try_send(ws, LoginOkMessage(rating=rating, username=claims.username, token=message.token))
        return claims.username, rating, claims

    if isinstance(message, RegisterMessage):
        result = await accounts_client.register(message.username, message.password)
    else:
        result = await accounts_client.login(message.username, message.password)
    await _try_send(ws, _login_response(result, message.username))
    if not result.success:
        return None
    claims = auth_token.verify_token(result.token)
    return message.username, result.rating, claims


async def _pump_lobby_message(matchmaking_client: MatchmakingClient, connection_id: str, ws: ServerConnection) -> bool:
    """Reads exactly one lobby message and forwards it to the
    Matchmaking Service. Returns False if the real client socket itself
    closed while waiting for it (a genuine disconnect) - True otherwise,
    so the caller keeps racing lobby-vs-push (see _handle_connection).
    Fire-and-forget: whatever this message produces (an ordinary reply,
    a routing signal, or nothing at all) arrives later over this
    connection's Pub/Sub channel, never as this call's own return
    value - matchmaking_service.py's /message endpoint never sends a
    meaningful body back for exactly that reason."""
    try:
        raw = await ws.recv()
    except ConnectionClosed:
        return False
    await matchmaking_client.send_message(connection_id, raw)
    return True


async def _try_send_raw(ws: ServerConnection, raw: str) -> None:
    """Transport: forwards an already-serialized wire message straight
    to the real client socket - used for anything the Matchmaking
    Service published (it already ran serialize_message() itself
    before publishing, see matchmaking_service.py's _RemoteConnection),
    so there's nothing left to encode here, only to relay."""
    try:
        await ws.send(raw)
    except Exception as error:
        logger.debug("send failed on %s: %s", ws.remote_address, error)


async def _pump(src: Any, dst: Any) -> None:
    """One direction of a relay session's byte pipe - raw, undecoded:
    the Gateway never needs to know what a relayed message means, only
    that it needs to reach the other side (see _run_relay_session)."""
    try:
        async for raw in src:
            await dst.send(raw)
    except Exception as error:
        logger.debug("relay pump ended: %s", error)


async def _resolve_shard_address(
    routing: shard_protocol.RoutingMessage, shard_host: str, shard_port: int, room_shard_registry: RoomShardRegistry
) -> Tuple[str, int]:
    """HostSeatMessage (a brand-new room) always uses the fixed
    shard_host/shard_port - there is no registry entry yet to look up
    (placement, not routing - see room_shard_registry.py's own
    docstring on that distinction; today it's also moot, since there is
    only ever one Game Shard to place a new room on regardless).
    ReconnectMessage/SpectateMessage name an *existing* room_id, so
    resolve it dynamically instead of assuming it's still the same
    fixed shard - the whole point of Server_Design.md section 3's
    registry. Falls back to the fixed address if the registry somehow
    has no entry (the room's lease already expired, or this worker
    never actually registered it) - the Shard itself is still the one
    that decides whether the reconnect/spectate is actually valid."""
    if isinstance(routing, (shard_protocol.ReconnectMessage, shard_protocol.SpectateMessage)):
        address = await room_shard_registry.get(routing.room_id)
        if address is not None:
            host, port = address.rsplit(":", 1)
            return host, int(port)
    return shard_host, shard_port


async def _run_relay_session(
    ws: ServerConnection,
    routing: shard_protocol.RoutingMessage,
    shard_host: str,
    shard_port: int,
    room_shard_registry: RoomShardRegistry,
) -> bool:
    """Opens an outbound connection to the Game Shard, sends the one
    routing handshake message (Server_Design.md Stage 4a), then pumps
    raw bytes both directions until either side closes. Returns True
    if the real client socket is still open afterward (the Shard
    ended the session on its own - a rejected reconnect/spectate, or
    an ordinary "Back to Lobby" - so the caller goes back to lobby
    mode); False if the real client socket itself closed (a genuine
    disconnect, mid-relay)."""
    resolved_host, resolved_port = await _resolve_shard_address(routing, shard_host, shard_port, room_shard_registry)
    try:
        async with connect(f"ws://{resolved_host}:{resolved_port}") as shard_ws:
            await shard_ws.send(shard_protocol.send_routing_message(routing))
            client_to_shard = asyncio.create_task(_pump(ws, shard_ws))
            shard_to_client = asyncio.create_task(_pump(shard_ws, ws))
            await asyncio.wait({client_to_shard, shard_to_client}, return_when=asyncio.FIRST_COMPLETED)
            for task in (client_to_shard, shard_to_client):
                task.cancel()
    except Exception as error:
        logger.warning("relay session to the shard failed: %s", error)
    return ws.close_code is None


async def _handle_connection(
    matchmaking_client: MatchmakingClient,
    accounts_client: AccountsClient,
    ws: ServerConnection,
    shard_host: str,
    shard_port: int,
    redis_client: Redis,
    room_shard_registry: RoomShardRegistry,
) -> None:
    auth = await _authenticate(ws, accounts_client, redis_client)
    if auth is None:
        return  # never enters the lobby - bad login or the connection dropped before completing it
    username, _, claims = auth
    ACTIVE_CONNECTIONS.inc()

    # A fresh id per connection, known only to this Gateway and the
    # Matchmaking Service it tells - the two ends of the Redis Pub/Sub
    # channel replacing the in-memory relay_queues this Gateway used
    # when it shared a process with Matchmaker directly.
    connection_id = uuid.uuid4().hex
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"mm:{connection_id}")
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    drain_task = asyncio.create_task(_drain_pubsub(pubsub, queue))

    try:
        # Subscribed *before* this call (above), so nothing on_connect
        # publishes synchronously (a rejection's LoginFailedMessage, or a
        # reconnect's routing signal) can be missed - Redis Pub/Sub never
        # replays a message to a subscriber that joined after it was sent.
        accepted = await matchmaking_client.connect(connection_id, username, claims)
        if not accepted:
            # already connected from another window - the Matchmaking
            # Service already published the LoginFailedMessage reply.
            try:
                item = await asyncio.wait_for(queue.get(), timeout=5.0)
                if item["kind"] == "reply":
                    await _try_send_raw(ws, item["raw"])
            except asyncio.TimeoutError:
                logger.warning("connect was rejected but no reply arrived for %s", username)
            return

        while True:
            lobby_task = asyncio.create_task(_pump_lobby_message(matchmaking_client, connection_id, ws))
            push_task = asyncio.create_task(queue.get())
            done, pending = await asyncio.wait({lobby_task, push_task}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()

            # Checked in this order deliberately, same reasoning as
            # before this moved to a network queue: a connection's own
            # SeekGameMessage/JoinRoomMessage can trigger its *own* match
            # synchronously inside the very HTTP call lobby_task is
            # awaiting, so both tasks can resolve in the same wait()
            # cycle - handling lobby_task first would risk processing a
            # push meant for *this* iteration one loop late.
            if push_task in done:
                item = push_task.result()
                if item["kind"] == "routing":
                    routing = shard_protocol.deserialize_routing(item["routing"])
                    still_open = await _run_relay_session(ws, routing, shard_host, shard_port, room_shard_registry)
                    if not still_open:
                        break
                    await matchmaking_client.leave_relay(connection_id)
                    continue
                if item["kind"] == "close":
                    await ws.close()
                    break
                await _try_send_raw(ws, item["raw"])  # kind == "reply"
                continue

            if not lobby_task.result():
                break  # the real client socket closed
    finally:
        drain_task.cancel()
        await pubsub.aclose()
        await matchmaking_client.disconnect(connection_id)
        ACTIVE_CONNECTIONS.dec()


async def run(
    host: str = HOST,
    port: int = PORT,
    accounts_service_url: str = ACCOUNTS_SERVICE_URL,
    shard_host: str = SHARD_HOST,
    shard_port: int = SHARD_PORT,
    matchmaking_service_url: str = MATCHMAKING_SERVICE_URL,
    namespace: str = "",
) -> None:
    # namespace must match the Shard's own GameAllocator namespace (see
    # game_shard.py's GameShard, default "") - both processes share one
    # Redis room_shard_registry. Production leaves this at the shared ""
    # default; tests pass a unique value to isolate themselves on one
    # Redis server (see tests/unit/conftest.py's shard_address fixture).
    accounts_client = get_accounts_client(accounts_service_url)
    matchmaking_client = get_matchmaking_client(matchmaking_service_url)
    # A second, independent Redis client from the Matchmaking Service's
    # own (see redis_client.py's own non-singleton rationale) - used for
    # the Stage 1b revocation check and this connection's Pub/Sub channel.
    redis_client = get_redis_client()
    room_shard_registry = RoomShardRegistry(redis_client, namespace)

    async def handler(ws: ServerConnection) -> None:
        await _handle_connection(
            matchmaking_client, accounts_client, ws, shard_host, shard_port, redis_client, room_shard_registry
        )

    async with serve(handler, host, port):
        logger.info("Kung Fu Chess server listening on ws://%s:%s", host, port)
        await asyncio.Future()  # runs until the process is killed


def main() -> None:
    configure_logging(LOG_FILE)
    start_metrics_server()
    asyncio.run(run())


if __name__ == "__main__":
    main()

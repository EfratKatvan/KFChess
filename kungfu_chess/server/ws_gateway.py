from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional, Tuple, Union

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
from kungfu_chess.server.matchmaker import Matchmaker
from kungfu_chess.server.messages import (
    LoginFailedMessage,
    LoginMessage,
    LoginOkMessage,
    RegisterMessage,
    TokenLoginMessage,
)
from kungfu_chess.server.redis_client import get_client as get_redis_client
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
directly), then hands every subsequent raw message to the Matchmaker
while the connection is in "lobby mode". Stage 4a (section 19): once
Matchmaker signals a match/room-join/reconnect/spectate via
on_enter_relay, this module opens its own outbound connection to the
Game Shard and switches that connection into "relay mode" - pumping
raw bytes both directions between the real client socket and the
Shard - until the Shard ends that session, at which point the
connection goes back to lobby mode. No game or matchmaking logic
lives here, only transport/protocol/routing."""


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


async def _pump_lobby_message(matchmaker: Matchmaker, ws: ServerConnection) -> bool:
    """Reads and dispatches exactly one lobby message. Returns False if
    the real client socket itself closed while waiting for it (a
    genuine disconnect) - True otherwise, so the caller keeps racing
    lobby-vs-relay (see _handle_connection)."""
    try:
        raw = await ws.recv()
    except ConnectionClosed:
        return False
    await matchmaker.on_message(ws, raw)
    return True


async def _pump(src: Any, dst: Any) -> None:
    """One direction of a relay session's byte pipe - raw, undecoded:
    the Gateway never needs to know what a relayed message means, only
    that it needs to reach the other side (see _run_relay_session)."""
    try:
        async for raw in src:
            await dst.send(raw)
    except Exception as error:
        logger.debug("relay pump ended: %s", error)


async def _run_relay_session(
    ws: ServerConnection, routing: shard_protocol.RoutingMessage, shard_host: str, shard_port: int
) -> bool:
    """Opens an outbound connection to the Game Shard, sends the one
    routing handshake message (Server_Design.md Stage 4a), then pumps
    raw bytes both directions until either side closes. Returns True
    if the real client socket is still open afterward (the Shard
    ended the session on its own - a rejected reconnect/spectate, or
    an ordinary "Back to Lobby" - so the caller goes back to lobby
    mode); False if the real client socket itself closed (a genuine
    disconnect, mid-relay)."""
    try:
        async with connect(f"ws://{shard_host}:{shard_port}") as shard_ws:
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
    matchmaker: Matchmaker,
    accounts_client: AccountsClient,
    ws: ServerConnection,
    relay_queues: Dict[ServerConnection, "asyncio.Queue[shard_protocol.RoutingMessage]"],
    shard_host: str,
    shard_port: int,
    redis_client: Redis,
) -> None:
    auth = await _authenticate(ws, accounts_client, redis_client)
    if auth is None:
        return  # never enters the lobby - bad login or the connection dropped before completing it
    username, _, claims = auth

    relay_queues[ws] = asyncio.Queue()
    accepted = await matchmaker.on_connect(ws, username, claims)
    if not accepted:
        del relay_queues[ws]
        return  # already connected from another window - matchmaker sent LoginFailedMessage itself

    try:
        while True:
            lobby_task = asyncio.create_task(_pump_lobby_message(matchmaker, ws))
            relay_task = asyncio.create_task(relay_queues[ws].get())
            done, pending = await asyncio.wait({lobby_task, relay_task}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()

            # Checked in this order deliberately: a connection's own
            # SeekGameMessage/JoinRoomMessage can trigger its *own* match
            # synchronously, inside the very call that also handles that
            # lobby message (see Matchmaker._start_seeking/_join_room) -
            # so both tasks can resolve in the same wait() cycle. Handling
            # lobby_task first would silently discard that relay request
            # (already popped off the queue by relay_task, never acted
            # on). lobby_task's own result needs no such care if skipped
            # here - matchmaker.on_message already fully handled the
            # message before returning; the boolean result is just
            # "did the socket stay open," safe to pick up again next loop.
            if relay_task in done:
                routing = relay_task.result()
                still_open = await _run_relay_session(ws, routing, shard_host, shard_port)
                if not still_open:
                    break
                await matchmaker.on_leave_relay(ws)
                continue

            if not lobby_task.result():
                break  # the real client socket closed
    finally:
        del relay_queues[ws]
        await matchmaker.on_disconnect(ws)


async def run(
    host: str = HOST,
    port: int = PORT,
    accounts_service_url: str = ACCOUNTS_SERVICE_URL,
    shard_host: str = SHARD_HOST,
    shard_port: int = SHARD_PORT,
    namespace: str = "",
) -> None:
    # namespace must match the Shard's own GameAllocator/RoomRegistry
    # namespace (game_shard.py's GameShard, default "") - both processes
    # share one Redis. Production leaves this at the shared "" default;
    # tests pass a unique value to isolate themselves on one Redis server
    # (see tests/unit/conftest.py's shard_address fixture).
    accounts_client = get_accounts_client(accounts_service_url)
    # A second, independent Redis client from Matchmaker's own (see
    # redis_client.py's own non-singleton rationale) - used only for the
    # revocation-existence check on a TokenLoginMessage (Stage 1b).
    redis_client = get_redis_client()
    relay_queues: Dict[ServerConnection, "asyncio.Queue[shard_protocol.RoutingMessage]"] = {}
    matchmaker = Matchmaker(
        accounts_client=accounts_client,
        on_enter_relay=lambda ws, routing: relay_queues[ws].put_nowait(routing),
        namespace=namespace,
    )

    async def handler(ws: ServerConnection) -> None:
        await _handle_connection(matchmaker, accounts_client, ws, relay_queues, shard_host, shard_port, redis_client)

    async with serve(handler, host, port):
        logger.info("Kung Fu Chess server listening on ws://%s:%s", host, port)
        await asyncio.Future()  # runs until the process is killed


def main() -> None:
    configure_logging(LOG_FILE)
    asyncio.run(run())


if __name__ == "__main__":
    main()

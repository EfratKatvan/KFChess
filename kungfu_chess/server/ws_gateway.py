from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, Tuple, Union

from websockets.asyncio.server import ServerConnection, serve

from kungfu_chess.logging_config import configure_logging
from kungfu_chess.server import accounts
from kungfu_chess.server.accounts_client import ACCOUNTS_SERVICE_URL, AccountsClient
from kungfu_chess.server.accounts_client import get_client as get_accounts_client
from kungfu_chess.server.matchmaker import Matchmaker
from kungfu_chess.server.messages import LoginFailedMessage, LoginMessage, LoginOkMessage, RegisterMessage
from kungfu_chess.server.serialization import deserialize_message, serialize_message

HOST = "localhost"
PORT = 8765
LOG_FILE = "ws_gateway.log"

logger = logging.getLogger(__name__)

"""The WS Gateway (Server_Design.md section 1's "WS Gateway" row,
section 14 row 2, section 14.2): the live-connection entry point - it
accepts the socket, drives the login/register handshake (over HTTP to
the Accounts/Ratings API Service via AccountsClient, never sqlite3
directly), then hands every subsequent raw message to the Matchmaker.
No game or matchmaking logic lives here, only transport/protocol/
routing - Stage 2 (section 19) is exactly this file existing as its
own module, separate from Matchmaker/GameRoom, ahead of it ever running
as its own deployable unit (still one process for now: Matchmaker is
constructed and called in-process below, not yet over the wire)."""


async def _try_send(ws: ServerConnection, message: Any) -> None:
    """Transport: best-effort send - a closed/closing socket shouldn't
    blow up the caller, but the failure is still worth a log line
    instead of vanishing silently."""
    try:
        await ws.send(serialize_message(message))
    except Exception as error:
        logger.debug("send failed on %s: %s", ws.remote_address, error)


async def _recv_login_message(ws: ServerConnection) -> Optional[Union[LoginMessage, RegisterMessage]]:
    """Transport + protocol: reads exactly one message off the wire and
    checks it's a login-or-register request (see network_client_view.py's
    shell username/password prompt, sent right after connecting, which
    the player chose Login or Register for). Returns None - logging why
    - for anything that isn't: a socket that closed before sending
    anything, a malformed payload, or a message of the wrong type sent
    before login completed. No model or presentation logic lives here."""
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

    if not isinstance(message, (LoginMessage, RegisterMessage)):
        logger.warning("expected a login or register message first, got %s", type(message).__name__)
        return None
    return message


def _login_response(result: accounts.AuthResult) -> Any:
    """Presentation: turns the model's AuthResult into the wire message
    the client understands - pure, no I/O, no knowledge of sockets.
    Shared by both login and register, since a successful register
    leaves the player logged in the same way a successful login does."""
    if not result.success:
        return LoginFailedMessage(reason=result.reason or "login failed")
    return LoginOkMessage(rating=result.rating)


async def _authenticate(ws: ServerConnection, accounts_client: AccountsClient) -> Optional[Tuple[str, int]]:
    """Application: orchestrates one login/register by calling each
    layer in turn - transport/protocol (_recv_login_message), model
    (accounts_client.login or accounts_client.register, chosen by the
    request's own type - an HTTP call to the Accounts/Ratings API
    Service, not a direct accounts.py/sqlite3 call, per Server_Design.md
    section 6), presentation (_login_response), then transport again
    (_try_send) - without any layer's logic living inside another.
    Returns the authenticated (username, rating), or None if the
    connection should be dropped (bad credentials, username already
    taken, or anything else went wrong before login completed)."""
    message = await _recv_login_message(ws)
    if message is None:
        return None

    if isinstance(message, RegisterMessage):
        result = await accounts_client.register(message.username, message.password)
    else:
        result = await accounts_client.login(message.username, message.password)
    await _try_send(ws, _login_response(result))
    if not result.success:
        return None
    return message.username, result.rating


async def _handle_connection(matchmaker: Matchmaker, accounts_client: AccountsClient, ws: ServerConnection) -> None:
    auth = await _authenticate(ws, accounts_client)
    if auth is None:
        return  # never enters the lobby - bad login or the connection dropped before completing it
    username, _ = auth

    accepted = await matchmaker.on_connect(ws, username)
    if not accepted:
        return  # already connected from another window - matchmaker sent LoginFailedMessage itself

    try:
        async for raw in ws:
            await matchmaker.on_message(ws, raw)
    finally:
        await matchmaker.on_disconnect(ws)


async def run(host: str = HOST, port: int = PORT, accounts_service_url: str = ACCOUNTS_SERVICE_URL) -> None:
    accounts_client = get_accounts_client(accounts_service_url)
    matchmaker = Matchmaker(accounts_client=accounts_client)
    async with serve(lambda ws: _handle_connection(matchmaker, accounts_client, ws), host, port):
        logger.info("Kung Fu Chess server listening on ws://%s:%s", host, port)
        await asyncio.Future()  # runs until the process is killed


def main() -> None:
    configure_logging(LOG_FILE)
    asyncio.run(run())


if __name__ == "__main__":
    main()

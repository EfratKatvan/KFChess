from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, Tuple, Union

from websockets.asyncio.server import ServerConnection, serve

from kungfu_chess.logging_config import configure_logging
from kungfu_chess.server import accounts
from kungfu_chess.server.matchmaker import Matchmaker
from kungfu_chess.server.messages import LoginFailedMessage, LoginMessage, LoginOkMessage, RegisterMessage
from kungfu_chess.server.serialization import deserialize_message, serialize_message

HOST = "localhost"
PORT = 8765
LOG_FILE = "server.log"

logger = logging.getLogger(__name__)


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


async def _authenticate(ws: ServerConnection, db_path: str) -> Optional[Tuple[str, int]]:
    """Application: orchestrates one login/register by calling each
    layer in turn - transport/protocol (_recv_login_message), model
    (accounts.login or accounts.register, chosen by the request's own
    type), presentation (_login_response), then transport again
    (_try_send) - without any layer's logic living inside another.
    Returns the authenticated (username, rating), or None if the
    connection should be dropped (bad credentials, username already
    taken, or anything else went wrong before login completed)."""
    message = await _recv_login_message(ws)
    if message is None:
        return None

    if isinstance(message, RegisterMessage):
        result = accounts.register(db_path, message.username, message.password)
    else:
        result = accounts.login(db_path, message.username, message.password)
    await _try_send(ws, _login_response(result))
    if not result.success:
        return None
    return message.username, result.rating


async def _handle_connection(matchmaker: Matchmaker, db_path: str, ws: ServerConnection) -> None:
    auth = await _authenticate(ws, db_path)
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


async def run(host: str = HOST, port: int = PORT, db_path: str = accounts.DEFAULT_DB_PATH) -> None:
    accounts.init_db(db_path)
    matchmaker = Matchmaker(db_path=db_path)
    async with serve(lambda ws: _handle_connection(matchmaker, db_path, ws), host, port):
        logger.info("Kung Fu Chess server listening on ws://%s:%s", host, port)
        await asyncio.Future()  # runs until the process is killed


def main() -> None:
    configure_logging(LOG_FILE)
    asyncio.run(run())


if __name__ == "__main__":
    main()

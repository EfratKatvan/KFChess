from __future__ import annotations

import asyncio
from typing import Any, Optional

from websockets.asyncio.server import ServerConnection, serve

from kungfu_chess.server import accounts
from kungfu_chess.server.matchmaker import Matchmaker
from kungfu_chess.server.messages import LoginFailedMessage, LoginMessage, LoginOkMessage
from kungfu_chess.server.serialization import deserialize_message, serialize_message

HOST = "localhost"
PORT = 8765


async def _try_send(ws: ServerConnection, message: Any) -> None:
    try:
        await ws.send(serialize_message(message))
    except Exception:
        pass


async def _authenticate(ws: ServerConnection, db_path: str) -> Optional[str]:
    """Waits for the connection's first message, which must be a login
    request (see network_client_view.py's shell username/password
    prompt, sent right after connecting) - returns the authenticated
    username, or None if the connection should be dropped (bad
    credentials, or anything else went wrong before login completed)."""
    try:
        raw = await ws.recv()
    except Exception:
        return None

    try:
        message = deserialize_message(raw)
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(message, LoginMessage):
        return None

    result = accounts.authenticate(db_path, message.username, message.password)
    if not result.success:
        await _try_send(ws, LoginFailedMessage(reason=result.reason or "login failed"))
        return None

    await _try_send(ws, LoginOkMessage(rating=result.rating))
    return message.username


async def _handle_connection(matchmaker: Matchmaker, db_path: str, ws: ServerConnection) -> None:
    username = await _authenticate(ws, db_path)
    if username is None:
        return  # never enters matchmaking - bad login or the connection dropped before completing it

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
        print(f"Kung Fu Chess server listening on ws://{host}:{port}")
        await asyncio.Future()  # runs until the process is killed


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()

from __future__ import annotations

import asyncio

from websockets.asyncio.server import ServerConnection, serve

from kungfu_chess.server.matchmaker import Matchmaker

HOST = "localhost"
PORT = 8765


async def _handle_connection(matchmaker: Matchmaker, ws: ServerConnection) -> None:
    await matchmaker.on_connect(ws)
    try:
        async for raw in ws:
            await matchmaker.on_message(ws, raw)
    finally:
        await matchmaker.on_disconnect(ws)


async def run(host: str = HOST, port: int = PORT) -> None:
    matchmaker = Matchmaker()
    async with serve(lambda ws: _handle_connection(matchmaker, ws), host, port):
        print(f"Kung Fu Chess server listening on ws://{host}:{port}")
        await asyncio.Future()  # runs until the process is killed


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()

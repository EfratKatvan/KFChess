from __future__ import annotations

import asyncio
import threading
from typing import Iterator

import pytest
from aiohttp.test_utils import TestServer

from kungfu_chess.server.accounts_service import create_app

"""Shared test infrastructure for the Accounts/Ratings API Service
(Stage 1, Server_Design.md section 19): a real aiohttp server, not a
mock, the same "no over-mocking" standard Stage 0's tests already hold
Redis to. Every test that used to construct Matchmaker/GameRoom with a
db_path now needs an actual running accounts_service to talk to over
HTTP.

Starting that server inside each test's own asyncio.run() would work,
but tearing it down cleanly needs the same event loop it was created
on - awkward to thread through ~90 existing test bodies. Instead, one
background thread runs its own persistent event loop for the whole
test session; each test asks it to start/stop a fresh aiohttp
TestServer bound to that test's own db_path fixture, on its own free
port. The AccountsClient a test actually exercises is still created
inside the test's own asyncio.run() (see accounts_client.py's own note
on why an aiohttp.ClientSession can't be shared across event loops) -
only the *server* side lives on the shared background loop, since it's
reached over a real OS socket from the client side, not anything
loop-bound."""


class _BackgroundLoop:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self._thread.start()

    def run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result()


_background = _BackgroundLoop()


@pytest.fixture
def accounts_base_url(db_path) -> Iterator[str]:
    """The base URL of a fresh accounts_service instance, bound to this
    test's own db_path fixture - pass straight to AccountsClient(...)."""

    async def _start() -> TestServer:
        server = TestServer(create_app(db_path))
        await server.start_server()
        return server

    async def _stop(server: TestServer) -> None:
        await server.close()

    server = _background.run(_start())
    yield str(server.make_url("/")).rstrip("/")
    _background.run(_stop(server))

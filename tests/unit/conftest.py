from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable, Dict, Iterator, Tuple

import pytest
from aiohttp.test_utils import TestServer
from websockets.asyncio.server import Server, ServerConnection, serve

from kungfu_chess.server import ws_gateway
from kungfu_chess.server.accounts_client import AccountsClient
from kungfu_chess.server.accounts_service import create_app
from kungfu_chess.server.game_shard import GameShard
from kungfu_chess.server.matchmaker import Matchmaker
from kungfu_chess.server.redis_client import get_client as get_redis_client

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


@pytest.fixture
def shard_address(accounts_base_url) -> Iterator[Callable[[str], Tuple[str, int]]]:
    """A factory: shard_address(namespace) starts a real GameShard (Stage
    4a, Server_Design.md sections 2/3/15) on the same shared background
    loop as accounts_base_url, bound to a free localhost port, and
    returns (host, port). `namespace` must match the Redis namespace of
    whatever Matchmaker the test is also driving, the same way
    test_game_allocator.py's `_make_allocator` shares a namespace with
    its own caller - a real running service over a real OS socket, not
    a mock, same standard as accounts_base_url above."""
    started: list[Server] = []

    async def _start(namespace: str) -> Server:
        shard = GameShard(
            accounts_client=AccountsClient(accounts_base_url), redis_client=get_redis_client(), namespace=namespace
        )
        return await serve(shard.handle_connection, "localhost", 0)

    def _factory(namespace: str) -> Tuple[str, int]:
        server = _background.run(_start(namespace))
        started.append(server)
        return "localhost", server.sockets[0].getsockname()[1]

    yield _factory

    async def _stop_all() -> None:
        for server in started:
            server.close()
            await server.wait_closed()

    _background.run(_stop_all())


@pytest.fixture
def gateway_address(accounts_base_url) -> Iterator[Callable[[str, str, int], Tuple[str, int]]]:
    """A factory: gateway_address(namespace, shard_host, shard_port)
    starts a real WS Gateway (Stage 4a) on the shared background loop,
    wired to the given Shard address and Redis namespace (must match
    whatever shard_address(namespace) the test also started). The third
    real-socket leg alongside accounts_base_url/shard_address - together
    they let a test drive a genuine client all the way through
    login -> match/room -> relay -> Shard-hosted GameRoom, over actual
    OS sockets, proving the process boundary Stage 4a introduces."""
    started: list[Server] = []

    async def _start(namespace: str, shard_host: str, shard_port: int) -> Server:
        accounts_client = AccountsClient(accounts_base_url)
        relay_queues: Dict[ServerConnection, "asyncio.Queue[Any]"] = {}
        matchmaker = Matchmaker(
            accounts_client=accounts_client,
            on_enter_relay=lambda ws, routing: relay_queues[ws].put_nowait(routing),
            namespace=namespace,
        )

        redis_client = get_redis_client()

        async def handler(ws: ServerConnection) -> None:
            await ws_gateway._handle_connection(
                matchmaker, accounts_client, ws, relay_queues, shard_host, shard_port, redis_client
            )

        return await serve(handler, "localhost", 0)

    def _factory(namespace: str, shard_host: str, shard_port: int) -> Tuple[str, int]:
        server = _background.run(_start(namespace, shard_host, shard_port))
        started.append(server)
        return "localhost", server.sockets[0].getsockname()[1]

    yield _factory

    async def _stop_all() -> None:
        for server in started:
            server.close()
            await server.wait_closed()

    _background.run(_stop_all())

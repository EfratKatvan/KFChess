from __future__ import annotations

import asyncio
import threading
import uuid
from typing import Callable, Iterator, Tuple

import pytest
from aiohttp.test_utils import TestServer
from websockets.asyncio.server import Server, ServerConnection, serve

from kungfu_chess.server import accounts, accounts_db, matchmaking_service, ws_gateway
from kungfu_chess.server.accounts_client import AccountsClient
from kungfu_chess.server.accounts_service import create_app
from kungfu_chess.server.game_shard import GameShard
from kungfu_chess.server.matchmaking_client import MatchmakingClient
from kungfu_chess.server.redis_client import get_client as get_redis_client
from kungfu_chess.server.room_shard_registry import RoomShardRegistry

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
def db_path() -> Iterator[str]:
    """A fresh, throwaway Postgres schema per test (Server_Design.md
    section 6) - the direct replacement for the old fresh-SQLite-file-
    per-test isolation, now that accounts_db.py talks to a single shared
    Postgres instance instead of a local file. Kept named `db_path`,
    not `schema`, even though its value is now a schema name - dozens of
    existing call sites across this suite already pass it under this
    name into functions whose own parameter is `schema`; positional
    arguments don't care what the caller's local variable is called."""
    schema = f"test_{uuid.uuid4().hex}"
    accounts.init_db(schema)
    yield schema
    accounts_db.drop_schema(schema)


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
    accounts_clients: list[AccountsClient] = []
    redis_clients: list = []

    async def _start(namespace: str) -> Server:
        accounts_client = AccountsClient(accounts_base_url)
        accounts_clients.append(accounts_client)
        redis_client = get_redis_client()
        redis_clients.append(redis_client)
        shard = GameShard(accounts_client=accounts_client, redis_client=redis_client, namespace=namespace)
        server = await serve(shard.handle_connection, "localhost", 0)
        # The real port isn't known until after serve() actually binds
        # it (0 means "OS, pick one") - so the advertised address (what
        # ws_gateway.py's room_shard_registry lookup will resolve a
        # reconnect/spectate to) can only be set now, not at
        # construction time. Safe: no room is allocated until real
        # traffic arrives, well after this fixture returns.
        shard.set_shard_address(f"localhost:{server.sockets[0].getsockname()[1]}")
        return server

    def _factory(namespace: str) -> Tuple[str, int]:
        server = _background.run(_start(namespace))
        started.append(server)
        return "localhost", server.sockets[0].getsockname()[1]

    yield _factory

    async def _stop_all() -> None:
        for server in started:
            server.close()
            await server.wait_closed()
        # An unclosed aiohttp.ClientSession/redis connection left open on
        # _background's own persistent, session-long event loop doesn't
        # just print a GC warning - it can leave a keep-alive connection
        # aiohttp's own AppRunner.cleanup() (see matchmaking_service.py's
        # own TestServer.close() in gateway_address below) still
        # considers "active", stalling that shutdown for its own
        # multi-second grace period. Closing every client this fixture
        # itself created is what actually prevents that, not just tidier
        # teardown output.
        for accounts_client in accounts_clients:
            await accounts_client.close()
        for redis_client in redis_clients:
            await redis_client.aclose()

    _background.run(_stop_all())


@pytest.fixture
def gateway_address(accounts_base_url) -> Iterator[Callable[[str, str, int], Tuple[str, int]]]:
    """A factory: gateway_address(namespace, shard_host, shard_port)
    starts a real WS Gateway (Stage 4a) *and* a real Matchmaking Service
    (the process-split this fixture's own docstring below used to lack -
    see Server_Design.md section 19's Stage 5 note) on the shared
    background loop, wired to the given Shard address and sharing one
    Redis namespace with it (must match whatever shard_address(namespace)
    the test also started). The third real-socket leg alongside
    accounts_base_url/shard_address - together they let a test drive a
    genuine client all the way through login -> match/room -> relay ->
    Shard-hosted GameRoom, over actual OS sockets and a real HTTP+Pub/Sub
    round trip to the Matchmaking Service, proving every process
    boundary this design introduces, not just the Shard's."""
    started: list[Server] = []
    matchmaking_servers: list[TestServer] = []
    accounts_clients: list[AccountsClient] = []
    matchmaking_clients: list[MatchmakingClient] = []
    redis_clients: list = []

    async def _start(namespace: str, shard_host: str, shard_port: int) -> Server:
        accounts_client = AccountsClient(accounts_base_url)
        accounts_clients.append(accounts_client)
        matchmaking_accounts_client = AccountsClient(accounts_base_url)
        accounts_clients.append(matchmaking_accounts_client)
        matchmaking_redis_client = get_redis_client()
        redis_clients.append(matchmaking_redis_client)
        matchmaking_app = matchmaking_service.create_app(
            accounts_client=matchmaking_accounts_client, redis_client=matchmaking_redis_client, namespace=namespace
        )
        matchmaking_server = TestServer(matchmaking_app)
        await matchmaking_server.start_server()
        matchmaking_servers.append(matchmaking_server)
        matchmaking_client = MatchmakingClient(str(matchmaking_server.make_url("/")).rstrip("/"))
        matchmaking_clients.append(matchmaking_client)

        redis_client = get_redis_client()
        redis_clients.append(redis_client)
        room_shard_registry = RoomShardRegistry(redis_client, namespace)

        async def handler(ws: ServerConnection) -> None:
            await ws_gateway._handle_connection(
                matchmaking_client, accounts_client, ws, shard_host, shard_port, redis_client, room_shard_registry
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
        for matchmaking_server in matchmaking_servers:
            await matchmaking_server.close()
        # Same reasoning as shard_address's own teardown above - every
        # client this fixture constructed (there are five: two
        # AccountsClients, two Redis clients, one MatchmakingClient) gets
        # closed here, not left for GC to eventually warn about.
        for matchmaking_client in matchmaking_clients:
            await matchmaking_client.close()
        for accounts_client in accounts_clients:
            await accounts_client.close()
        for redis_client in redis_clients:
            await redis_client.aclose()

    _background.run(_stop_all())

import asyncio
import uuid

from kungfu_chess.server import accounts, accounts_db, auth_token, protocol, shard_protocol
from kungfu_chess.server.accounts_client import AccountsClient
from kungfu_chess.server.messages import LoginMessage, RegisterMessage, RestartMessage, TokenLoginMessage
from kungfu_chess.server.redis_client import get_client as get_redis_client
from kungfu_chess.server.room_shard_registry import RoomShardRegistry
from kungfu_chess.server.serialization import serialize_message
from kungfu_chess.server.ws_gateway import _authenticate, _resolve_shard_address
from tests.unit.test_matchmaker import FakeConnection, _last_type


class QueuedConnection(FakeConnection):
    """A FakeConnection that also has messages queued up for recv() -
    _authenticate reads the connection's first message directly, unlike
    Matchmaker/GameRoom which only ever call send()."""

    def __init__(self, name: str, incoming) -> None:
        super().__init__(name)
        self._incoming = list(incoming)

    async def recv(self) -> str:
        return self._incoming.pop(0)


class FakeRedis:
    """A dict-backed stand-in for the one thing _authenticate needs from
    Redis - an async existence check for a revoked token's jti (Stage
    1b). These tests are about the auth handshake itself, not
    revocation storage, so a real Redis isn't warranted here - unlike
    test_relay_integration.py's end-to-end logout/revocation tests,
    which do use a real one."""

    def __init__(self, revoked_jtis=()) -> None:
        self._revoked = set(revoked_jtis)

    async def exists(self, key: str) -> bool:
        return key in self._revoked


def test_register_message_creates_a_new_username_and_returns_it(db_path, accounts_base_url):
    asyncio.run(_new_user_register_scenario(db_path, accounts_base_url))


async def _new_user_register_scenario(db_path, accounts_base_url):
    ws = QueuedConnection("client", [serialize_message(RegisterMessage(username="efrat", password="pw"))])

    accounts_client = AccountsClient(accounts_base_url)
    username, rating, claims = await _authenticate(ws, accounts_client, FakeRedis())

    assert (username, rating) == ("efrat", accounts.STARTING_RATING)
    assert claims.username == "efrat"
    assert _last_type(ws) == protocol.LOGIN_OK
    assert ws.sent[-1]["rating"] == accounts.STARTING_RATING
    assert ws.sent[-1]["username"] == "efrat"
    assert ws.sent[-1]["token"]  # a real signed session token, not just a bare rating


def test_register_message_rejects_a_username_that_is_already_taken(db_path, accounts_base_url):
    asyncio.run(_duplicate_register_scenario(db_path, accounts_base_url))


async def _duplicate_register_scenario(db_path, accounts_base_url):
    accounts.register(db_path, "efrat", "hunter2")
    ws = QueuedConnection("client", [serialize_message(RegisterMessage(username="efrat", password="hunter2"))])

    accounts_client = AccountsClient(accounts_base_url)
    result = await _authenticate(ws, accounts_client, FakeRedis())

    assert result is None
    assert _last_type(ws) == protocol.LOGIN_FAILED


def test_login_message_rejects_a_username_that_was_never_registered(db_path, accounts_base_url):
    asyncio.run(_unknown_username_login_scenario(db_path, accounts_base_url))


async def _unknown_username_login_scenario(db_path, accounts_base_url):
    ws = QueuedConnection("client", [serialize_message(LoginMessage(username="efrat", password="pw"))])

    accounts_client = AccountsClient(accounts_base_url)
    result = await _authenticate(ws, accounts_client, FakeRedis())

    assert result is None
    assert _last_type(ws) == protocol.LOGIN_FAILED


def test_login_message_accepts_a_returning_user_with_the_right_password(db_path, accounts_base_url):
    asyncio.run(_returning_user_scenario(db_path, accounts_base_url))


async def _returning_user_scenario(db_path, accounts_base_url):
    accounts.register(db_path, "efrat", "hunter2")
    ws = QueuedConnection("client", [serialize_message(LoginMessage(username="efrat", password="hunter2"))])

    accounts_client = AccountsClient(accounts_base_url)
    username, rating, claims = await _authenticate(ws, accounts_client, FakeRedis())

    assert username == "efrat"
    assert claims.jti  # a real token was issued and decoded for tracking (see matchmaker.py's _token_of)
    assert _last_type(ws) == protocol.LOGIN_OK


def test_login_message_rejects_the_wrong_password(db_path, accounts_base_url):
    asyncio.run(_wrong_password_scenario(db_path, accounts_base_url))


async def _wrong_password_scenario(db_path, accounts_base_url):
    accounts.register(db_path, "efrat", "hunter2")
    ws = QueuedConnection("client", [serialize_message(LoginMessage(username="efrat", password="wrong"))])

    accounts_client = AccountsClient(accounts_base_url)
    result = await _authenticate(ws, accounts_client, FakeRedis())

    assert result is None
    assert _last_type(ws) == protocol.LOGIN_FAILED


def test_authenticate_rejects_a_first_message_that_is_neither_login_nor_register(db_path, accounts_base_url):
    asyncio.run(_non_login_first_scenario(db_path, accounts_base_url))


async def _non_login_first_scenario(db_path, accounts_base_url):
    ws = QueuedConnection("client", [serialize_message(RestartMessage())])

    accounts_client = AccountsClient(accounts_base_url)
    result = await _authenticate(ws, accounts_client, FakeRedis())

    assert result is None
    assert ws.sent == []  # no response sent - the connection is just dropped


def test_authenticate_handles_garbage_first_message_without_raising(db_path, accounts_base_url):
    asyncio.run(_garbage_first_message_scenario(db_path, accounts_base_url))


async def _garbage_first_message_scenario(db_path, accounts_base_url):
    ws = QueuedConnection("client", ["not json at all"])

    accounts_client = AccountsClient(accounts_base_url)
    result = await _authenticate(ws, accounts_client, FakeRedis())

    assert result is None


def test_token_login_with_a_valid_unrevoked_token_succeeds(db_path, accounts_base_url):
    asyncio.run(_valid_token_login_scenario(db_path, accounts_base_url))


async def _valid_token_login_scenario(db_path, accounts_base_url):
    accounts.register(db_path, "efrat", "hunter2")
    token = auth_token.issue_token("efrat", accounts.STARTING_RATING)
    ws = QueuedConnection("client", [serialize_message(TokenLoginMessage(token=token, username="efrat"))])

    accounts_client = AccountsClient(accounts_base_url)
    username, rating, claims = await _authenticate(ws, accounts_client, FakeRedis())

    assert username == "efrat"
    assert rating == accounts.STARTING_RATING
    assert claims.username == "efrat"
    assert _last_type(ws) == protocol.LOGIN_OK
    assert ws.sent[-1]["token"] == token  # the same token is handed back, not rotated


async def _fresh_rating_scenario(db_path, accounts_base_url):
    """The token's own embedded rating claim is stale the instant a
    game finishes after it was issued - _authenticate must fetch fresh
    rather than trust it (see ws_gateway.py's own comment)."""
    accounts.register(db_path, "efrat", "hunter2")
    stale_token = auth_token.issue_token("efrat", 1200)
    accounts_db.write_ratings(db_path, "efrat", 1300, "efrat", 1300)  # rating moved after the token was issued
    ws = QueuedConnection("client", [serialize_message(TokenLoginMessage(token=stale_token, username="efrat"))])

    accounts_client = AccountsClient(accounts_base_url)
    username, rating, claims = await _authenticate(ws, accounts_client, FakeRedis())

    assert rating == 1300  # not the stale 1200 embedded in the token
    assert claims.rating == 1200  # the claim itself is untouched - only the returned rating is refreshed


def test_token_login_uses_the_current_rating_not_the_stale_claim(db_path, accounts_base_url):
    asyncio.run(_fresh_rating_scenario(db_path, accounts_base_url))


def test_token_login_with_a_tampered_token_is_rejected(db_path, accounts_base_url):
    asyncio.run(_tampered_token_login_scenario(db_path, accounts_base_url))


async def _tampered_token_login_scenario(db_path, accounts_base_url):
    ws = QueuedConnection("client", [serialize_message(TokenLoginMessage(token="not-a-real-token", username="efrat"))])

    accounts_client = AccountsClient(accounts_base_url)
    result = await _authenticate(ws, accounts_client, FakeRedis())

    assert result is None
    assert _last_type(ws) == protocol.LOGIN_FAILED


def test_token_login_with_a_revoked_token_is_rejected(db_path, accounts_base_url):
    asyncio.run(_revoked_token_login_scenario(db_path, accounts_base_url))


async def _revoked_token_login_scenario(db_path, accounts_base_url):
    accounts.register(db_path, "efrat", "hunter2")
    token = auth_token.issue_token("efrat", accounts.STARTING_RATING)
    claims = auth_token.verify_token(token)
    ws = QueuedConnection("client", [serialize_message(TokenLoginMessage(token=token, username="efrat"))])

    accounts_client = AccountsClient(accounts_base_url)
    result = await _authenticate(ws, accounts_client, FakeRedis(revoked_jtis={f"revoked:token:{claims.jti}"}))

    assert result is None
    assert _last_type(ws) == protocol.LOGIN_FAILED


def test_host_seat_uses_the_registry_address_when_agones_already_wrote_one():
    """Server_Design.md section 3, Stage 7: matchmaker.py's own Agones
    allocation call now writes a brand-new room's resolved address into
    the registry *before* either seat's HostSeatMessage is ever sent -
    so this must resolve dynamically, exactly like Reconnect/Spectate
    already did, not ignore the registry the way it used to when
    placement and routing were still the same trivial "there is only
    one Game Shard" fact."""
    asyncio.run(_host_seat_uses_registry_scenario())


async def _host_seat_uses_registry_scenario():
    registry = RoomShardRegistry(get_redis_client(), namespace=uuid.uuid4().hex)
    await registry.acquire("room-1", "agones-picked-shard:9999")
    routing = shard_protocol.HostSeatMessage(room_id="room-1", color="white", username="a", opponent_username="b")

    host, port = await _resolve_shard_address(routing, "fixed-host", 1234, registry)

    assert (host, port) == ("agones-picked-shard", 9999)


def test_host_seat_falls_back_to_the_fixed_address_with_no_registry_entry():
    """No Agones integration configured at all (docker-compose, most
    tests) never populates this key ahead of time - HostSeatMessage
    must still fall back to the fixed shard_host/shard_port exactly as
    it always did in that world."""
    asyncio.run(_host_seat_falls_back_scenario())


async def _host_seat_falls_back_scenario():
    registry = RoomShardRegistry(get_redis_client(), namespace=uuid.uuid4().hex)
    routing = shard_protocol.HostSeatMessage(room_id="room-1", color="white", username="a", opponent_username="b")

    host, port = await _resolve_shard_address(routing, "fixed-host", 1234, registry)

    assert (host, port) == ("fixed-host", 1234)


def test_reconnect_resolves_to_the_registry_address_not_the_fixed_fallback():
    """The actual point of this whole mechanism: an existing room's
    real owner - discovered dynamically - must win even when it
    disagrees with whatever fixed shard_host/shard_port this Gateway
    process happened to start with."""
    asyncio.run(_reconnect_uses_registry_scenario())


async def _reconnect_uses_registry_scenario():
    registry = RoomShardRegistry(get_redis_client(), namespace=uuid.uuid4().hex)
    await registry.acquire("room-1", "real-shard:8767")
    routing = shard_protocol.ReconnectMessage(room_id="room-1", color="white", username="alice")

    host, port = await _resolve_shard_address(routing, "wrong-fixed-host", 1234, registry)

    assert (host, port) == ("real-shard", 8767)


def test_spectate_resolves_to_the_registry_address_not_the_fixed_fallback():
    asyncio.run(_spectate_uses_registry_scenario())


async def _spectate_uses_registry_scenario():
    registry = RoomShardRegistry(get_redis_client(), namespace=uuid.uuid4().hex)
    await registry.acquire("room-1", "real-shard:8767")
    routing = shard_protocol.SpectateMessage(room_id="room-1", username="carol")

    host, port = await _resolve_shard_address(routing, "wrong-fixed-host", 1234, registry)

    assert (host, port) == ("real-shard", 8767)


def test_reconnect_with_no_registry_entry_falls_back_to_the_fixed_address():
    """The room's lease already expired (or was never this worker's to
    begin with) - the Shard itself still decides whether a reconnect
    attempt against the fixed fallback is actually valid; this
    function's only job is picking an address to *try*."""
    asyncio.run(_reconnect_falls_back_scenario())


async def _reconnect_falls_back_scenario():
    registry = RoomShardRegistry(get_redis_client(), namespace=uuid.uuid4().hex)
    routing = shard_protocol.ReconnectMessage(room_id="never-registered", color="white", username="alice")

    host, port = await _resolve_shard_address(routing, "fixed-host", 1234, registry)

    assert (host, port) == ("fixed-host", 1234)

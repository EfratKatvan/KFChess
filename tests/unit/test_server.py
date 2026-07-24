import asyncio

import pytest

from kungfu_chess.server import accounts, protocol
from kungfu_chess.server.messages import LoginMessage, RegisterMessage, RestartMessage
from kungfu_chess.server.serialization import serialize_message
from kungfu_chess.server.server import _authenticate
from tests.unit.test_matchmaker import FakeConnection, _last_type


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test_users.db")
    accounts.init_db(path)
    return path


class QueuedConnection(FakeConnection):
    """A FakeConnection that also has messages queued up for recv() -
    _authenticate reads the connection's first message directly, unlike
    Matchmaker/GameRoom which only ever call send()."""

    def __init__(self, name: str, incoming) -> None:
        super().__init__(name)
        self._incoming = list(incoming)

    async def recv(self) -> str:
        return self._incoming.pop(0)


def test_register_message_creates_a_new_username_and_returns_it(db_path):
    asyncio.run(_new_user_register_scenario(db_path))


async def _new_user_register_scenario(db_path):
    ws = QueuedConnection("client", [serialize_message(RegisterMessage(username="efrat", password="pw"))])

    result = await _authenticate(ws, db_path)

    assert result == ("efrat", accounts.STARTING_RATING)
    assert _last_type(ws) == protocol.LOGIN_OK
    assert ws.sent[-1]["rating"] == accounts.STARTING_RATING


def test_register_message_rejects_a_username_that_is_already_taken(db_path):
    asyncio.run(_duplicate_register_scenario(db_path))


async def _duplicate_register_scenario(db_path):
    accounts.register(db_path, "efrat", "hunter2")
    ws = QueuedConnection("client", [serialize_message(RegisterMessage(username="efrat", password="hunter2"))])

    result = await _authenticate(ws, db_path)

    assert result is None
    assert _last_type(ws) == protocol.LOGIN_FAILED


def test_login_message_rejects_a_username_that_was_never_registered(db_path):
    asyncio.run(_unknown_username_login_scenario(db_path))


async def _unknown_username_login_scenario(db_path):
    ws = QueuedConnection("client", [serialize_message(LoginMessage(username="efrat", password="pw"))])

    result = await _authenticate(ws, db_path)

    assert result is None
    assert _last_type(ws) == protocol.LOGIN_FAILED


def test_login_message_accepts_a_returning_user_with_the_right_password(db_path):
    asyncio.run(_returning_user_scenario(db_path))


async def _returning_user_scenario(db_path):
    accounts.register(db_path, "efrat", "hunter2")
    ws = QueuedConnection("client", [serialize_message(LoginMessage(username="efrat", password="hunter2"))])

    result = await _authenticate(ws, db_path)

    assert result[0] == "efrat"
    assert _last_type(ws) == protocol.LOGIN_OK


def test_login_message_rejects_the_wrong_password(db_path):
    asyncio.run(_wrong_password_scenario(db_path))


async def _wrong_password_scenario(db_path):
    accounts.register(db_path, "efrat", "hunter2")
    ws = QueuedConnection("client", [serialize_message(LoginMessage(username="efrat", password="wrong"))])

    result = await _authenticate(ws, db_path)

    assert result is None
    assert _last_type(ws) == protocol.LOGIN_FAILED


def test_authenticate_rejects_a_first_message_that_is_neither_login_nor_register(db_path):
    asyncio.run(_non_login_first_scenario(db_path))


async def _non_login_first_scenario(db_path):
    ws = QueuedConnection("client", [serialize_message(RestartMessage())])

    result = await _authenticate(ws, db_path)

    assert result is None
    assert ws.sent == []  # no response sent - the connection is just dropped


def test_authenticate_handles_garbage_first_message_without_raising(db_path):
    asyncio.run(_garbage_first_message_scenario(db_path))


async def _garbage_first_message_scenario(db_path):
    ws = QueuedConnection("client", ["not json at all"])

    result = await _authenticate(ws, db_path)

    assert result is None

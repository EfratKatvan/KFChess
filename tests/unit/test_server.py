import asyncio
import json

import pytest

from kungfu_chess.server import accounts, protocol
from kungfu_chess.server.messages import LoginMessage, RestartMessage
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


def test_authenticate_registers_a_new_username_and_returns_it(db_path):
    asyncio.run(_new_user_scenario(db_path))


async def _new_user_scenario(db_path):
    ws = QueuedConnection("client", [serialize_message(LoginMessage(username="efrat", password="pw"))])

    username = await _authenticate(ws, db_path)

    assert username == "efrat"
    assert _last_type(ws) == protocol.LOGIN_OK
    assert ws.sent[-1]["rating"] == accounts.STARTING_RATING


def test_authenticate_accepts_a_returning_user_with_the_right_password(db_path):
    asyncio.run(_returning_user_scenario(db_path))


async def _returning_user_scenario(db_path):
    accounts.authenticate(db_path, "efrat", "hunter2")
    ws = QueuedConnection("client", [serialize_message(LoginMessage(username="efrat", password="hunter2"))])

    username = await _authenticate(ws, db_path)

    assert username == "efrat"
    assert _last_type(ws) == protocol.LOGIN_OK


def test_authenticate_rejects_the_wrong_password(db_path):
    asyncio.run(_wrong_password_scenario(db_path))


async def _wrong_password_scenario(db_path):
    accounts.authenticate(db_path, "efrat", "hunter2")
    ws = QueuedConnection("client", [serialize_message(LoginMessage(username="efrat", password="wrong"))])

    username = await _authenticate(ws, db_path)

    assert username is None
    assert _last_type(ws) == protocol.LOGIN_FAILED


def test_authenticate_rejects_a_first_message_that_is_not_a_login(db_path):
    asyncio.run(_non_login_first_scenario(db_path))


async def _non_login_first_scenario(db_path):
    ws = QueuedConnection("client", [serialize_message(RestartMessage())])

    username = await _authenticate(ws, db_path)

    assert username is None
    assert ws.sent == []  # no response sent - the connection is just dropped


def test_authenticate_handles_garbage_first_message_without_raising(db_path):
    asyncio.run(_garbage_first_message_scenario(db_path))


async def _garbage_first_message_scenario(db_path):
    ws = QueuedConnection("client", ["not json at all"])

    username = await _authenticate(ws, db_path)

    assert username is None

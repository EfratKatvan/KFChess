import asyncio
import uuid

import pytest

from kungfu_chess.server import accounts, game_allocator
from kungfu_chess.server.accounts_client import AccountsClient
from kungfu_chess.server.game_allocator import GameAllocator, RoomAllocationError
from kungfu_chess.server.redis_client import get_client as get_redis_client
from tests.unit.test_matchmaker import FakeConnection


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test_users.db")
    accounts.init_db(path)
    return path


def _make_allocator(accounts_base_url: str) -> GameAllocator:
    """A fresh GameAllocator per test, on a unique Redis namespace - the
    same test-isolation seam matchmaker.py/rooms.py already use."""
    return GameAllocator(
        accounts_client=AccountsClient(accounts_base_url),
        redis_client=get_redis_client(),
        namespace=uuid.uuid4().hex,
    )


def test_allocate_acquires_a_redis_lease_for_the_room(db_path, accounts_base_url):
    asyncio.run(_allocate_acquires_a_lease(db_path, accounts_base_url))


async def _allocate_acquires_a_lease(db_path, accounts_base_url):
    allocator = _make_allocator(accounts_base_url)
    white, black = FakeConnection("alice"), FakeConnection("bob")

    room = await allocator.allocate(
        white_ws=white, white_username="alice", black_ws=black, black_username="bob", room_id="efrat-room"
    )

    key = allocator._lease_key("efrat-room")
    assert await allocator._redis.get(key) == allocator._worker_id
    ttl_ms = await allocator._redis.pttl(key)
    assert 0 < ttl_ms <= game_allocator.LEASE_TTL_MS

    await allocator._release_lease("efrat-room")
    room.stop()


def test_allocating_an_already_leased_room_id_is_rejected(db_path, accounts_base_url):
    asyncio.run(_double_allocate_scenario(db_path, accounts_base_url))


async def _double_allocate_scenario(db_path, accounts_base_url):
    """The exact failure mode section 3 exists to prevent: two
    placement attempts for the same room must never both succeed - one
    worker (or, today, one caller) has to lose the race."""
    allocator = _make_allocator(accounts_base_url)
    white, black = FakeConnection("alice"), FakeConnection("bob")
    room = await allocator.allocate(
        white_ws=white, white_username="alice", black_ws=black, black_username="bob", room_id="efrat-room"
    )

    with pytest.raises(RoomAllocationError):
        await allocator.allocate(
            white_ws=white, white_username="alice", black_ws=black, black_username="bob", room_id="efrat-room"
        )

    await allocator._release_lease("efrat-room")
    room.stop()


def test_ending_the_game_releases_the_lease(db_path, accounts_base_url):
    asyncio.run(_release_on_game_over_scenario(db_path, accounts_base_url))


async def _release_on_game_over_scenario(db_path, accounts_base_url):
    allocator = _make_allocator(accounts_base_url)
    white, black = FakeConnection("alice"), FakeConnection("bob")
    room = await allocator.allocate(
        white_ws=white, white_username="alice", black_ws=black, black_username="bob", room_id="efrat-room"
    )
    key = allocator._lease_key("efrat-room")
    assert await allocator._redis.exists(key)

    room._engine.resign()  # force game-over, same trick test_game_room.py/test_matchmaker.py use
    await room.leave(white)  # the "Back to Lobby" path - releases the lease via GameAllocator.release()

    assert not await allocator._redis.exists(key)
    assert "efrat-room" not in allocator._lease_renewal_tasks


def test_lease_is_renewed_before_it_would_otherwise_expire(db_path, accounts_base_url, monkeypatch):
    monkeypatch.setattr(game_allocator, "LEASE_TTL_MS", 150)
    monkeypatch.setattr(game_allocator, "LEASE_RENEWAL_SECONDS", 0.05)
    asyncio.run(_lease_renewal_scenario(db_path, accounts_base_url))


async def _lease_renewal_scenario(db_path, accounts_base_url):
    allocator = _make_allocator(accounts_base_url)
    white, black = FakeConnection("alice"), FakeConnection("bob")
    room = await allocator.allocate(
        white_ws=white, white_username="alice", black_ws=black, black_username="bob", room_id="efrat-room"
    )
    key = allocator._lease_key("efrat-room")

    # Longer than the (shortened) TTL - without the heartbeat renewing
    # it, the key would have expired on its own by now.
    await asyncio.sleep(0.3)
    assert await allocator._redis.exists(key)

    await allocator._release_lease("efrat-room")
    room.stop()

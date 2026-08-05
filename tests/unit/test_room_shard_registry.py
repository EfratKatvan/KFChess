import asyncio
import uuid

from kungfu_chess.server import room_shard_registry
from kungfu_chess.server.redis_client import get_client as get_redis_client
from kungfu_chess.server.room_shard_registry import RoomShardRegistry


def _make_registry() -> RoomShardRegistry:
    return RoomShardRegistry(get_redis_client(), namespace=uuid.uuid4().hex)


def test_get_with_no_entry_returns_none():
    asyncio.run(_no_entry_scenario())


async def _no_entry_scenario():
    registry = _make_registry()
    assert await registry.get("no-such-room") is None


def test_acquire_then_get_returns_the_stored_address():
    asyncio.run(_acquire_then_get_scenario())


async def _acquire_then_get_scenario():
    registry = _make_registry()
    acquired = await registry.acquire("room-1", "game-shard-1:8767")
    assert acquired is True
    assert await registry.get("room-1") == "game-shard-1:8767"


def test_acquiring_an_already_held_room_id_fails():
    """Server_Design.md section 3's own mutual-exclusion requirement -
    a second worker must never be able to steal a still-live room's
    lease out from under the worker that already holds it."""
    asyncio.run(_double_acquire_scenario())


async def _double_acquire_scenario():
    registry = _make_registry()
    await registry.acquire("room-1", "game-shard-1:8767")

    acquired_again = await registry.acquire("room-1", "game-shard-2:8767")

    assert acquired_again is False
    assert await registry.get("room-1") == "game-shard-1:8767"  # unchanged - the first holder wasn't displaced


def test_renew_by_the_current_holder_extends_the_lease():
    asyncio.run(_renew_by_holder_scenario())


async def _renew_by_holder_scenario():
    registry = _make_registry()
    await registry.acquire("room-1", "game-shard-1:8767", ttl_ms=200)

    renewed = await registry.renew("room-1", "game-shard-1:8767", ttl_ms=5000)

    assert renewed is True
    await asyncio.sleep(0.3)  # past the original (short) ttl, well under the renewed one
    assert await registry.get("room-1") == "game-shard-1:8767"


def test_renew_by_a_different_holder_is_rejected():
    """The atomic compare-and-renew (Server_Design.md section 3): a
    worker that doesn't actually hold this room's lease must never be
    able to extend it - only the exact address currently stored may
    renew, closing the race a plain GET-then-PEXPIRE would leave open."""
    asyncio.run(_renew_by_wrong_holder_scenario())


async def _renew_by_wrong_holder_scenario():
    registry = _make_registry()
    await registry.acquire("room-1", "game-shard-1:8767")

    renewed = await registry.renew("room-1", "game-shard-2:8767")

    assert renewed is False


def test_release_removes_the_entry():
    asyncio.run(_release_scenario())


async def _release_scenario():
    registry = _make_registry()
    await registry.acquire("room-1", "game-shard-1:8767")

    await registry.release("room-1")

    assert await registry.get("room-1") is None


def test_confirm_or_acquire_with_no_entry_behaves_like_acquire():
    asyncio.run(_confirm_or_acquire_fresh_scenario())


async def _confirm_or_acquire_fresh_scenario():
    registry = _make_registry()

    confirmed = await registry.confirm_or_acquire("room-1", "game-shard-1:8767")

    assert confirmed is True
    assert await registry.get("room-1") == "game-shard-1:8767"


def test_confirm_or_acquire_by_the_address_already_stored_succeeds():
    """Server_Design.md section 3, Stage 7: matchmaker.py's own Agones
    allocation call writes this room's address first; the replica
    Agones actually picked then confirms that same address via
    GameAllocator.allocate() - this must succeed, not collide with the
    pre-write the way a plain acquire(nx=True) would."""
    asyncio.run(_confirm_or_acquire_matching_scenario())


async def _confirm_or_acquire_matching_scenario():
    registry = _make_registry()
    await registry.confirm_or_acquire("room-1", "game-shard-1:8767")

    confirmed_again = await registry.confirm_or_acquire("room-1", "game-shard-1:8767")

    assert confirmed_again is True
    assert await registry.get("room-1") == "game-shard-1:8767"


def test_confirm_or_acquire_by_a_different_address_is_rejected():
    """The genuine conflict case - a *different* worker's address is
    already there - must still fail, same as the old acquire()'s own
    mutual-exclusion guarantee."""
    asyncio.run(_confirm_or_acquire_conflict_scenario())


async def _confirm_or_acquire_conflict_scenario():
    registry = _make_registry()
    await registry.confirm_or_acquire("room-1", "game-shard-1:8767")

    confirmed = await registry.confirm_or_acquire("room-1", "game-shard-2:8767")

    assert confirmed is False
    assert await registry.get("room-1") == "game-shard-1:8767"  # unchanged


def test_lease_expires_on_its_own_without_renewal():
    """No clean shutdown required for correctness (Server_Design.md
    section 3) - a crashed worker simply stops renewing, and the lease
    lapses on its own TTL rather than needing anyone to notice the
    crash and explicitly release it."""
    asyncio.run(_expiry_scenario())


async def _expiry_scenario():
    registry = _make_registry()
    await registry.acquire("room-1", "game-shard-1:8767", ttl_ms=100)

    await asyncio.sleep(0.3)

    assert await registry.get("room-1") is None

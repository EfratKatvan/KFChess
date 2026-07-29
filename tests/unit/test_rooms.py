import asyncio
import uuid

import pytest

from kungfu_chess.server import protocol
from kungfu_chess.server.redis_client import get_client
from kungfu_chess.server.rooms import RoomError, RoomRegistry


def _make_registry() -> RoomRegistry:
    """A fresh RoomRegistry per test, on a unique Redis namespace - the
    same test-isolation seam matchmaker.py uses (see its own __init__
    docstring): real Redis, but no two tests' rooms can ever collide."""
    return RoomRegistry(redis_client=get_client(), namespace=uuid.uuid4().hex)


def test_create_uses_the_players_chosen_name():
    asyncio.run(_create_uses_the_players_chosen_name())


async def _create_uses_the_players_chosen_name():
    registry = _make_registry()

    room = await registry.create("alice", "efrat-room")

    assert room.creator_username == "alice"
    assert room.room_id == "efrat-room"
    assert room.is_pending


def test_create_trims_surrounding_whitespace():
    asyncio.run(_create_trims_surrounding_whitespace())


async def _create_trims_surrounding_whitespace():
    registry = _make_registry()

    room = await registry.create("alice", "  efrat-room  ")

    assert room.room_id == "efrat-room"


def test_create_rejects_an_empty_name():
    asyncio.run(_create_rejects_an_empty_name())


async def _create_rejects_an_empty_name():
    registry = _make_registry()

    with pytest.raises(RoomError, match="room_name_required"):
        await registry.create("alice", "")


def test_create_rejects_a_whitespace_only_name():
    asyncio.run(_create_rejects_a_whitespace_only_name())


async def _create_rejects_a_whitespace_only_name():
    registry = _make_registry()

    with pytest.raises(RoomError, match="room_name_required"):
        await registry.create("alice", "   ")


def test_create_rejects_a_name_over_the_max_length():
    asyncio.run(_create_rejects_a_name_over_the_max_length())


async def _create_rejects_a_name_over_the_max_length():
    registry = _make_registry()
    too_long = "x" * (protocol.MAX_ROOM_ID_LENGTH + 1)

    with pytest.raises(RoomError, match="room_name_too_long"):
        await registry.create("alice", too_long)


def test_create_accepts_a_name_at_exactly_the_max_length():
    asyncio.run(_create_accepts_a_name_at_exactly_the_max_length())


async def _create_accepts_a_name_at_exactly_the_max_length():
    registry = _make_registry()
    exactly_max = "x" * protocol.MAX_ROOM_ID_LENGTH

    room = await registry.create("alice", exactly_max)

    assert room.room_id == exactly_max


def test_create_rejects_a_name_already_taken():
    asyncio.run(_create_rejects_a_name_already_taken())


async def _create_rejects_a_name_already_taken():
    registry = _make_registry()
    await registry.create("alice", "efrat-room")

    with pytest.raises(RoomError, match="room_name_taken"):
        await registry.create("bob", "efrat-room")


def test_create_is_case_insensitive_for_the_taken_check():
    asyncio.run(_create_is_case_insensitive_for_the_taken_check())


async def _create_is_case_insensitive_for_the_taken_check():
    registry = _make_registry()
    await registry.create("alice", "Efrat-Room")

    with pytest.raises(RoomError, match="room_name_taken"):
        await registry.create("bob", "efrat-room")


def test_create_preserves_the_creators_exact_display_casing():
    asyncio.run(_create_preserves_the_creators_exact_display_casing())


async def _create_preserves_the_creators_exact_display_casing():
    registry = _make_registry()

    room = await registry.create("alice", "Efrat-Room")

    assert room.room_id == "Efrat-Room"  # not upper/lower-cased for display


def test_creating_a_second_room_by_the_same_username_is_rejected():
    asyncio.run(_creating_a_second_room_by_the_same_username_is_rejected())


async def _creating_a_second_room_by_the_same_username_is_rejected():
    registry = _make_registry()
    await registry.create("alice", "room-one")

    with pytest.raises(RoomError, match="already_in_a_room"):
        await registry.create("alice", "room-two")


def test_first_join_fills_the_opponent_seat():
    asyncio.run(_first_join_fills_the_opponent_seat())


async def _first_join_fills_the_opponent_seat():
    registry = _make_registry()
    room = await registry.create("alice", "efrat-room")

    joined = await registry.join(room.room_id, "bob")

    assert joined.opponent_username == "bob"
    assert not joined.is_pending
    assert joined.spectator_usernames == set()


def test_second_join_becomes_a_spectator():
    asyncio.run(_second_join_becomes_a_spectator())


async def _second_join_becomes_a_spectator():
    registry = _make_registry()
    room = await registry.create("alice", "efrat-room")
    await registry.join(room.room_id, "bob")

    joined = await registry.join(room.room_id, "carol")

    assert joined.opponent_username == "bob"
    assert joined.spectator_usernames == {"carol"}


def test_any_number_of_spectators_can_join():
    asyncio.run(_any_number_of_spectators_can_join())


async def _any_number_of_spectators_can_join():
    registry = _make_registry()
    room = await registry.create("alice", "efrat-room")
    await registry.join(room.room_id, "bob")

    await registry.join(room.room_id, "carol")
    joined = await registry.join(room.room_id, "dave")

    assert joined.spectator_usernames == {"carol", "dave"}


def test_join_is_case_insensitive_on_the_room_id():
    asyncio.run(_join_is_case_insensitive_on_the_room_id())


async def _join_is_case_insensitive_on_the_room_id():
    registry = _make_registry()
    room = await registry.create("alice", "Efrat-Room")

    joined = await registry.join(room.room_id.lower(), "bob")

    assert joined.opponent_username == "bob"


def test_join_works_with_the_exact_display_casing_too():
    asyncio.run(_join_works_with_the_exact_display_casing_too())


async def _join_works_with_the_exact_display_casing_too():
    registry = _make_registry()
    room = await registry.create("alice", "Efrat-Room")

    joined = await registry.join("Efrat-Room", "bob")

    assert joined.opponent_username == "bob"


def test_joining_an_unknown_room_id_raises_room_not_found():
    asyncio.run(_joining_an_unknown_room_id_raises_room_not_found())


async def _joining_an_unknown_room_id_raises_room_not_found():
    registry = _make_registry()

    with pytest.raises(RoomError, match="room_not_found"):
        await registry.join("nosuch", "bob")


def test_joining_while_already_in_a_room_is_rejected():
    asyncio.run(_joining_while_already_in_a_room_is_rejected())


async def _joining_while_already_in_a_room_is_rejected():
    registry = _make_registry()
    room = await registry.create("alice", "efrat-room")
    await registry.create("bob", "bobs-room")

    with pytest.raises(RoomError, match="already_in_a_room"):
        await registry.join(room.room_id, "bob")


def test_cancel_by_the_creator_while_pending_succeeds():
    asyncio.run(_cancel_by_the_creator_while_pending_succeeds())


async def _cancel_by_the_creator_while_pending_succeeds():
    registry = _make_registry()
    await registry.create("alice", "efrat-room")

    await registry.cancel("alice")

    assert await registry.room_for_username("alice") is None


def test_cancel_removes_the_room_entirely():
    asyncio.run(_cancel_removes_the_room_entirely())


async def _cancel_removes_the_room_entirely():
    registry = _make_registry()
    room = await registry.create("alice", "efrat-room")
    await registry.cancel("alice")

    with pytest.raises(RoomError, match="room_not_found"):
        await registry.join(room.room_id, "bob")


def test_cancel_frees_the_name_for_reuse():
    asyncio.run(_cancel_frees_the_name_for_reuse())


async def _cancel_frees_the_name_for_reuse():
    registry = _make_registry()
    await registry.create("alice", "efrat-room")
    await registry.cancel("alice")

    room = await registry.create("bob", "efrat-room")  # same name, now free again

    assert room.creator_username == "bob"


def test_cancel_by_a_non_creator_is_rejected():
    asyncio.run(_cancel_by_a_non_creator_is_rejected())


async def _cancel_by_a_non_creator_is_rejected():
    registry = _make_registry()
    room = await registry.create("alice", "efrat-room")
    await registry.join(room.room_id, "bob")

    with pytest.raises(RoomError, match="not_the_creator"):
        await registry.cancel("bob")


def test_cancel_after_the_room_started_is_rejected():
    asyncio.run(_cancel_after_the_room_started_is_rejected())


async def _cancel_after_the_room_started_is_rejected():
    registry = _make_registry()
    room = await registry.create("alice", "efrat-room")
    await registry.join(room.room_id, "bob")

    with pytest.raises(RoomError, match="already_started"):
        await registry.cancel("alice")


def test_cancel_by_someone_not_in_any_room_is_rejected():
    asyncio.run(_cancel_by_someone_not_in_any_room_is_rejected())


async def _cancel_by_someone_not_in_any_room_is_rejected():
    registry = _make_registry()

    with pytest.raises(RoomError, match="not_in_a_room"):
        await registry.cancel("alice")


def test_close_frees_creator_opponent_and_every_spectator():
    asyncio.run(_close_frees_creator_opponent_and_every_spectator())


async def _close_frees_creator_opponent_and_every_spectator():
    registry = _make_registry()
    room = await registry.create("alice", "efrat-room")
    await registry.join(room.room_id, "bob")
    await registry.join(room.room_id, "carol")

    await registry.close(room.room_id)

    assert await registry.room_for_username("alice") is None
    assert await registry.room_for_username("bob") is None
    assert await registry.room_for_username("carol") is None
    # every freed username can now create/join a new room
    await registry.create("alice", "efrat-room")


def test_close_on_an_already_gone_room_id_is_a_no_op():
    asyncio.run(_close_on_an_already_gone_room_id_is_a_no_op())


async def _close_on_an_already_gone_room_id_is_a_no_op():
    registry = _make_registry()

    await registry.close("nosuch")  # must not raise


def test_room_for_username_returns_none_for_a_stranger():
    asyncio.run(_room_for_username_returns_none_for_a_stranger())


async def _room_for_username_returns_none_for_a_stranger():
    registry = _make_registry()

    assert await registry.room_for_username("nobody") is None

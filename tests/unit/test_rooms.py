import pytest

from kungfu_chess.server import protocol
from kungfu_chess.server.rooms import RoomError, RoomRegistry


def test_create_uses_the_players_chosen_name():
    registry = RoomRegistry()

    room = registry.create("alice", "efrat-room")

    assert room.creator_username == "alice"
    assert room.room_id == "efrat-room"
    assert room.is_pending


def test_create_trims_surrounding_whitespace():
    registry = RoomRegistry()

    room = registry.create("alice", "  efrat-room  ")

    assert room.room_id == "efrat-room"


def test_create_rejects_an_empty_name():
    registry = RoomRegistry()

    with pytest.raises(RoomError, match="room_name_required"):
        registry.create("alice", "")


def test_create_rejects_a_whitespace_only_name():
    registry = RoomRegistry()

    with pytest.raises(RoomError, match="room_name_required"):
        registry.create("alice", "   ")


def test_create_rejects_a_name_over_the_max_length():
    registry = RoomRegistry()
    too_long = "x" * (protocol.MAX_ROOM_ID_LENGTH + 1)

    with pytest.raises(RoomError, match="room_name_too_long"):
        registry.create("alice", too_long)


def test_create_accepts_a_name_at_exactly_the_max_length():
    registry = RoomRegistry()
    exactly_max = "x" * protocol.MAX_ROOM_ID_LENGTH

    room = registry.create("alice", exactly_max)

    assert room.room_id == exactly_max


def test_create_rejects_a_name_already_taken():
    registry = RoomRegistry()
    registry.create("alice", "efrat-room")

    with pytest.raises(RoomError, match="room_name_taken"):
        registry.create("bob", "efrat-room")


def test_create_is_case_insensitive_for_the_taken_check():
    registry = RoomRegistry()
    registry.create("alice", "Efrat-Room")

    with pytest.raises(RoomError, match="room_name_taken"):
        registry.create("bob", "efrat-room")


def test_create_preserves_the_creators_exact_display_casing():
    registry = RoomRegistry()

    room = registry.create("alice", "Efrat-Room")

    assert room.room_id == "Efrat-Room"  # not upper/lower-cased for display


def test_creating_a_second_room_by_the_same_username_is_rejected():
    registry = RoomRegistry()
    registry.create("alice", "room-one")

    with pytest.raises(RoomError, match="already_in_a_room"):
        registry.create("alice", "room-two")


def test_first_join_fills_the_opponent_seat():
    registry = RoomRegistry()
    room = registry.create("alice", "efrat-room")

    joined = registry.join(room.room_id, "bob")

    assert joined.opponent_username == "bob"
    assert not joined.is_pending
    assert joined.spectator_usernames == set()


def test_second_join_becomes_a_spectator():
    registry = RoomRegistry()
    room = registry.create("alice", "efrat-room")
    registry.join(room.room_id, "bob")

    joined = registry.join(room.room_id, "carol")

    assert joined.opponent_username == "bob"
    assert joined.spectator_usernames == {"carol"}


def test_any_number_of_spectators_can_join():
    registry = RoomRegistry()
    room = registry.create("alice", "efrat-room")
    registry.join(room.room_id, "bob")

    registry.join(room.room_id, "carol")
    joined = registry.join(room.room_id, "dave")

    assert joined.spectator_usernames == {"carol", "dave"}


def test_join_is_case_insensitive_on_the_room_id():
    registry = RoomRegistry()
    room = registry.create("alice", "Efrat-Room")

    joined = registry.join(room.room_id.lower(), "bob")

    assert joined.opponent_username == "bob"


def test_join_works_with_the_exact_display_casing_too():
    registry = RoomRegistry()
    room = registry.create("alice", "Efrat-Room")

    joined = registry.join("Efrat-Room", "bob")

    assert joined.opponent_username == "bob"


def test_joining_an_unknown_room_id_raises_room_not_found():
    registry = RoomRegistry()

    with pytest.raises(RoomError, match="room_not_found"):
        registry.join("nosuch", "bob")


def test_joining_while_already_in_a_room_is_rejected():
    registry = RoomRegistry()
    room = registry.create("alice", "efrat-room")
    registry.create("bob", "bobs-room")

    with pytest.raises(RoomError, match="already_in_a_room"):
        registry.join(room.room_id, "bob")


def test_cancel_by_the_creator_while_pending_succeeds():
    registry = RoomRegistry()
    registry.create("alice", "efrat-room")

    registry.cancel("alice")

    assert registry.room_for_username("alice") is None


def test_cancel_removes_the_room_entirely():
    registry = RoomRegistry()
    room = registry.create("alice", "efrat-room")
    registry.cancel("alice")

    with pytest.raises(RoomError, match="room_not_found"):
        registry.join(room.room_id, "bob")


def test_cancel_frees_the_name_for_reuse():
    registry = RoomRegistry()
    registry.create("alice", "efrat-room")
    registry.cancel("alice")

    room = registry.create("bob", "efrat-room")  # same name, now free again

    assert room.creator_username == "bob"


def test_cancel_by_a_non_creator_is_rejected():
    registry = RoomRegistry()
    room = registry.create("alice", "efrat-room")
    registry.join(room.room_id, "bob")

    with pytest.raises(RoomError, match="not_the_creator"):
        registry.cancel("bob")


def test_cancel_after_the_room_started_is_rejected():
    registry = RoomRegistry()
    room = registry.create("alice", "efrat-room")
    registry.join(room.room_id, "bob")

    with pytest.raises(RoomError, match="already_started"):
        registry.cancel("alice")


def test_cancel_by_someone_not_in_any_room_is_rejected():
    registry = RoomRegistry()

    with pytest.raises(RoomError, match="not_in_a_room"):
        registry.cancel("alice")


def test_close_frees_creator_opponent_and_every_spectator():
    registry = RoomRegistry()
    room = registry.create("alice", "efrat-room")
    registry.join(room.room_id, "bob")
    registry.join(room.room_id, "carol")

    registry.close(room.room_id)

    assert registry.room_for_username("alice") is None
    assert registry.room_for_username("bob") is None
    assert registry.room_for_username("carol") is None
    # every freed username can now create/join a new room
    registry.create("alice", "efrat-room")


def test_close_on_an_already_gone_room_id_is_a_no_op():
    registry = RoomRegistry()

    registry.close("nosuch")  # must not raise


def test_room_for_username_returns_none_for_a_stranger():
    registry = RoomRegistry()

    assert registry.room_for_username("nobody") is None

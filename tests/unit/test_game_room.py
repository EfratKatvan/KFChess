import asyncio

import pytest

from kungfu_chess.engine.board_view_state import BoardViewState, PieceView
from kungfu_chess.model.piece import KING, WHITE, BLACK
from kungfu_chess.model.position import Position
from kungfu_chess.server import accounts, protocol
from kungfu_chess.server.accounts_client import AccountsClient
from kungfu_chess.server.game_room import GameRoom
from kungfu_chess.server.messages import ResignMessage, SelectOrMoveMessage
from tests.unit.test_matchmaker import FakeConnection, _last_type


def _make_room(db_path, accounts_base_url, white_ws=None, black_ws=None):
    accounts.register(db_path, "white_player", "pw")
    accounts.register(db_path, "black_player", "pw")
    return GameRoom(
        white_ws or FakeConnection("white"), "white_player",
        black_ws or FakeConnection("black"), "black_player",
        accounts_client=AccountsClient(accounts_base_url),
    )


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test_users.db")
    accounts.init_db(path)
    return path


def _view_state_with_survivor(color: str) -> BoardViewState:
    """A minimal game_over=True snapshot where only `color`'s king is
    still on the board - exactly what _apply_rating_update reads to
    decide who won."""
    return BoardViewState(
        width=8, height=8, game_over=True,
        pieces=(PieceView(position=Position(0, 4), color=color, kind=KING, visual_state="idle", elapsed_ms=0),),
    )


def test_match_found_sent_to_both_connections_on_start(db_path, accounts_base_url):
    asyncio.run(_start_scenario(db_path, accounts_base_url))


async def _start_scenario(db_path, accounts_base_url):
    room = _make_room(db_path, accounts_base_url)

    await room.start()

    white_ws, black_ws = room._connections[WHITE], room._connections[BLACK]
    assert _last_type(white_ws) == protocol.MATCH_FOUND
    assert white_ws.sent[-1]["color"] == WHITE
    assert white_ws.sent[-1]["white_username"] == "white_player"
    assert white_ws.sent[-1]["white_rating"] == accounts.STARTING_RATING
    assert white_ws.sent[-1]["black_username"] == "black_player"
    assert white_ws.sent[-1]["black_rating"] == accounts.STARTING_RATING
    assert _last_type(black_ws) == protocol.MATCH_FOUND
    assert black_ws.sent[-1]["color"] == BLACK

    room.stop()


def test_white_cannot_move_a_black_piece_through_the_room(db_path, accounts_base_url):
    asyncio.run(_gating_scenario(db_path, accounts_base_url))


async def _gating_scenario(db_path, accounts_base_url):
    white_ws, black_ws = FakeConnection("white"), FakeConnection("black")
    room = GameRoom(white_ws, "white_player", black_ws, "black_player", accounts_client=AccountsClient(accounts_base_url))
    await room.start()

    # A black pawn starts at row 1 in the standard starting position - white shouldn't be able to select it.
    await room.handle_message(WHITE, SelectOrMoveMessage(row=1, col=0))
    assert room._controllers[WHITE].selected_pos is None

    await room.handle_message(BLACK, SelectOrMoveMessage(row=1, col=0))
    assert room._controllers[BLACK].selected_pos is not None

    room.stop()


def test_apply_rating_update_credits_the_survivors_color_as_the_winner(db_path, accounts_base_url):
    asyncio.run(_rating_update_scenario(db_path, accounts_base_url))


async def _rating_update_scenario(db_path, accounts_base_url):
    accounts.register(db_path, "white_player", "pw")
    accounts.register(db_path, "black_player", "pw")

    white_ws, black_ws = FakeConnection("white"), FakeConnection("black")
    room = GameRoom(white_ws, "white_player", black_ws, "black_player", accounts_client=AccountsClient(accounts_base_url))
    await room.start()

    await room._apply_rating_update(_view_state_with_survivor(WHITE))  # only white's king survives

    assert accounts.get_rating(db_path, "white_player") == accounts.STARTING_RATING + accounts.ELO_K_FACTOR // 2
    assert accounts.get_rating(db_path, "black_player") == accounts.STARTING_RATING - accounts.ELO_K_FACTOR // 2

    room.stop()


def test_apply_rating_update_only_ever_applies_once_per_game(db_path, accounts_base_url):
    asyncio.run(_rating_update_once_scenario(db_path, accounts_base_url))


async def _rating_update_once_scenario(db_path, accounts_base_url):
    accounts.register(db_path, "white_player", "pw")
    accounts.register(db_path, "black_player", "pw")

    white_ws, black_ws = FakeConnection("white"), FakeConnection("black")
    room = GameRoom(white_ws, "white_player", black_ws, "black_player", accounts_client=AccountsClient(accounts_base_url))
    await room.start()

    view_state = _view_state_with_survivor(WHITE)
    await room._apply_rating_update(view_state)
    rating_after_first_call = accounts.get_rating(db_path, "white_player")

    await room._apply_rating_update(view_state)  # a second call must be a no-op (_rating_update_applied guard)
    rating_after_second_call = accounts.get_rating(db_path, "white_player")

    assert rating_after_first_call == rating_after_second_call

    room.stop()


# ==========================================
# Disconnect / reconnect / auto-resign
# ==========================================

def test_handle_disconnect_pauses_the_room_and_notifies_the_survivor(db_path, accounts_base_url):
    asyncio.run(_disconnect_scenario(db_path, accounts_base_url))


async def _disconnect_scenario(db_path, accounts_base_url):
    black_ws = FakeConnection("black")
    room = _make_room(db_path, accounts_base_url, black_ws=black_ws)
    await room.start()

    await room.handle_disconnect(WHITE)

    assert room._paused is True
    assert _last_type(black_ws) == protocol.OPPONENT_DISCONNECTED
    assert black_ws.sent[-1]["grace_seconds"] == protocol.DISCONNECT_GRACE_SECONDS

    room.stop()


def test_paused_room_does_not_advance_the_engine_clock(db_path, accounts_base_url):
    asyncio.run(_paused_clock_scenario(db_path, accounts_base_url))


async def _paused_clock_scenario(db_path, accounts_base_url):
    room = _make_room(db_path, accounts_base_url)
    await room.start()
    await room.handle_disconnect(WHITE)

    elapsed_before = room._engine._total_elapsed_ms
    room._last_tick -= 1.0  # pretend a full second has passed since the last tick
    await room._tick_once()
    elapsed_after = room._engine._total_elapsed_ms

    assert elapsed_after == elapsed_before  # engine.wait() was skipped entirely while paused

    room.stop()


# ==========================================
# Broadcast throttling - physics ticks every TICK_SECONDS, but the network
# send is throttled to BROADCAST_INTERVAL_SECONDS
# ==========================================

def test_tick_once_does_not_broadcast_again_before_the_interval_elapses(db_path, accounts_base_url):
    asyncio.run(_no_broadcast_yet_scenario(db_path, accounts_base_url))


async def _no_broadcast_yet_scenario(db_path, accounts_base_url):
    # Registration (now deliberately slow - see accounts.PBKDF2_ITERATIONS)
    # must happen before constructing GameRoom, not after - its
    # constructor starts the broadcast-throttle clock immediately, and
    # this test's whole premise is "nothing has broadcast yet" within a
    # tight ~67ms window right after that.
    white_ws, black_ws = FakeConnection("white"), FakeConnection("black")
    accounts.register(db_path, "white_player", "pw")
    accounts.register(db_path, "black_player", "pw")
    room = GameRoom(white_ws, "white_player", black_ws, "black_player", accounts_client=AccountsClient(accounts_base_url))
    await room.start()  # sends match_found - one message each, not a broadcast

    sent_count_after_start = len(white_ws.sent)
    await room._tick_once()  # immediately after start() - well within the throttle interval
    assert len(white_ws.sent) == sent_count_after_start  # no new "state" message yet

    room.stop()


def test_tick_once_broadcasts_once_the_interval_has_elapsed(db_path, accounts_base_url):
    asyncio.run(_broadcast_after_interval_scenario(db_path, accounts_base_url))


async def _broadcast_after_interval_scenario(db_path, accounts_base_url):
    from kungfu_chess.server.game_room import BROADCAST_INTERVAL_SECONDS

    room = _make_room(db_path, accounts_base_url)
    await room.start()
    white_ws = room._connections[WHITE]
    sent_count_after_start = len(white_ws.sent)

    room._last_broadcast -= BROADCAST_INTERVAL_SECONDS  # pretend the interval already elapsed
    await room._tick_once()

    assert len(white_ws.sent) == sent_count_after_start + 1
    assert _last_type(white_ws) == protocol.STATE

    room.stop()


def test_physics_advances_every_tick_regardless_of_the_broadcast_throttle(db_path, accounts_base_url):
    """The throttle only affects whether _broadcast() is called - engine.wait()
    must still run on every single _tick_once(), so motion timing stays accurate."""
    asyncio.run(_physics_unaffected_scenario(db_path, accounts_base_url))


async def _physics_unaffected_scenario(db_path, accounts_base_url):
    room = _make_room(db_path, accounts_base_url)
    await room.start()

    room._last_tick -= 1.0  # pretend a full second has passed
    elapsed_before = room._engine._total_elapsed_ms
    await room._tick_once()  # well within the broadcast throttle window - but physics must still run
    elapsed_after = room._engine._total_elapsed_ms

    assert elapsed_after > elapsed_before

    room.stop()


def test_try_reconnect_resumes_the_clock_and_notifies_the_survivor(db_path, accounts_base_url):
    asyncio.run(_reconnect_scenario(db_path, accounts_base_url))


async def _reconnect_scenario(db_path, accounts_base_url):
    black_ws = FakeConnection("black")
    room = _make_room(db_path, accounts_base_url, black_ws=black_ws)
    await room.start()
    await room.handle_disconnect(WHITE)

    new_white_ws = FakeConnection("white-new")
    reconnected = await room.try_reconnect(WHITE, new_white_ws)

    assert reconnected is True
    assert room._paused is False
    assert room.color_of(new_white_ws) == WHITE
    assert _last_type(black_ws) == protocol.OPPONENT_RECONNECTED
    assert _last_type(new_white_ws) == protocol.MATCH_FOUND  # re-learns its own color/username/rating
    assert new_white_ws.sent[-1]["color"] == WHITE

    room.stop()


def test_try_reconnect_rejects_the_wrong_color(db_path, accounts_base_url):
    asyncio.run(_reconnect_wrong_color_scenario(db_path, accounts_base_url))


async def _reconnect_wrong_color_scenario(db_path, accounts_base_url):
    room = _make_room(db_path, accounts_base_url)
    await room.start()
    await room.handle_disconnect(WHITE)

    reconnected = await room.try_reconnect(BLACK, FakeConnection("black-new"))

    assert reconnected is False

    room.stop()


def test_auto_resign_ends_the_game_and_credits_the_survivor(db_path, monkeypatch, accounts_base_url):
    monkeypatch.setattr(protocol, "DISCONNECT_GRACE_SECONDS", 0.05)
    asyncio.run(_auto_resign_scenario(db_path, accounts_base_url))


async def _auto_resign_scenario(db_path, accounts_base_url):
    room = _make_room(db_path, accounts_base_url)
    await room.start()

    await room.handle_disconnect(WHITE)  # black is the survivor
    await asyncio.sleep(0.15)

    assert room._engine.is_game_over() is True
    assert accounts.get_rating(db_path, "black_player") == accounts.STARTING_RATING + accounts.ELO_K_FACTOR // 2
    assert accounts.get_rating(db_path, "white_player") == accounts.STARTING_RATING - accounts.ELO_K_FACTOR // 2

    room.stop()


def test_resign_ends_the_game_and_credits_the_opponent(db_path, accounts_base_url):
    asyncio.run(_resign_scenario(db_path, accounts_base_url))


async def _resign_scenario(db_path, accounts_base_url):
    room = _make_room(db_path, accounts_base_url)
    await room.start()

    await room.handle_message(WHITE, ResignMessage())

    assert room._engine.is_game_over() is True
    assert accounts.get_rating(db_path, "black_player") == accounts.STARTING_RATING + accounts.ELO_K_FACTOR // 2
    assert accounts.get_rating(db_path, "white_player") == accounts.STARTING_RATING - accounts.ELO_K_FACTOR // 2

    room.stop()


def test_resign_after_game_over_is_a_no_op(db_path, accounts_base_url):
    asyncio.run(_resign_after_game_over_scenario(db_path, accounts_base_url))


async def _resign_after_game_over_scenario(db_path, accounts_base_url):
    room = _make_room(db_path, accounts_base_url)
    await room.start()

    await room.handle_message(WHITE, ResignMessage())  # black wins
    await room.handle_message(BLACK, ResignMessage())  # too late - the game already ended

    assert accounts.get_rating(db_path, "black_player") == accounts.STARTING_RATING + accounts.ELO_K_FACTOR // 2
    assert accounts.get_rating(db_path, "white_player") == accounts.STARTING_RATING - accounts.ELO_K_FACTOR // 2

    room.stop()


def test_leave_by_a_real_player_stops_the_room_and_returns_the_opponent(db_path, accounts_base_url):
    asyncio.run(_leave_scenario(db_path, accounts_base_url))


async def _leave_scenario(db_path, accounts_base_url):
    room = _make_room(db_path, accounts_base_url)
    await room.start()
    room._engine.resign()  # the game must already be over - Matchmaker._leave_room only calls this once it is

    also_leaving = await room.leave(room._connections[WHITE])

    assert also_leaving == {room._connections[BLACK]}
    await asyncio.sleep(0)
    assert room._tick_task.cancelled()


def test_leave_by_a_spectator_affects_no_one_else(db_path, accounts_base_url):
    asyncio.run(_spectator_leave_scenario(db_path, accounts_base_url))


async def _spectator_leave_scenario(db_path, accounts_base_url):
    room = _make_room(db_path, accounts_base_url)
    await room.start()
    room._engine.resign()
    spectator_ws = FakeConnection("spectator")
    await room.add_spectator(spectator_ws)

    also_leaving = await room.leave(spectator_ws)

    assert also_leaving == set()
    assert spectator_ws not in room._spectators
    await asyncio.sleep(0)
    assert not room._tick_task.cancelled()  # the two real players are still in their game

    room.stop()


def test_reconnecting_before_the_grace_period_cancels_the_auto_resign(db_path, monkeypatch, accounts_base_url):
    monkeypatch.setattr(protocol, "DISCONNECT_GRACE_SECONDS", 0.2)
    asyncio.run(_reconnect_cancels_resign_scenario(db_path, accounts_base_url))


async def _reconnect_cancels_resign_scenario(db_path, accounts_base_url):
    room = _make_room(db_path, accounts_base_url)
    await room.start()

    await room.handle_disconnect(WHITE)
    await room.try_reconnect(WHITE, FakeConnection("white-new"))
    await asyncio.sleep(0.3)  # past what the original grace period would have been

    assert room._engine.is_game_over() is False
    assert accounts.get_rating(db_path, "white_player") == accounts.STARTING_RATING
    assert accounts.get_rating(db_path, "black_player") == accounts.STARTING_RATING

    room.stop()


# ==========================================
# Spectators
# ==========================================

def test_add_spectator_sends_an_immediate_state_snapshot(db_path, accounts_base_url):
    asyncio.run(_add_spectator_scenario(db_path, accounts_base_url))


async def _add_spectator_scenario(db_path, accounts_base_url):
    room = _make_room(db_path, accounts_base_url)
    await room.start()
    spectator_ws = FakeConnection("spectator")

    await room.add_spectator(spectator_ws)

    assert _last_type(spectator_ws) == protocol.STATE  # doesn't wait for the next tick

    room.stop()


def test_spectator_state_message_has_no_personal_selection(db_path, accounts_base_url):
    asyncio.run(_spectator_state_shape_scenario(db_path, accounts_base_url))


async def _spectator_state_shape_scenario(db_path, accounts_base_url):
    room = _make_room(db_path, accounts_base_url)
    await room.start()
    spectator_ws = FakeConnection("spectator")

    await room.add_spectator(spectator_ws)

    sent = spectator_ws.sent[-1]
    assert sent["your_selected_pos"] is None
    assert sent["your_legal_destinations"] == []
    assert sent["your_invalid_target"] is None

    room.stop()


def test_spectator_receives_broadcasts_on_the_normal_tick_interval(db_path, accounts_base_url):
    asyncio.run(_spectator_broadcast_scenario(db_path, accounts_base_url))


async def _spectator_broadcast_scenario(db_path, accounts_base_url):
    from kungfu_chess.server.game_room import BROADCAST_INTERVAL_SECONDS

    room = _make_room(db_path, accounts_base_url)
    await room.start()
    spectator_ws = FakeConnection("spectator")
    await room.add_spectator(spectator_ws)
    sent_count_after_join = len(spectator_ws.sent)

    room._last_broadcast -= BROADCAST_INTERVAL_SECONDS
    await room._tick_once()

    assert len(spectator_ws.sent) == sent_count_after_join + 1
    assert _last_type(spectator_ws) == protocol.STATE

    room.stop()


def test_remove_spectator_stops_further_broadcasts_to_it(db_path, accounts_base_url):
    asyncio.run(_remove_spectator_scenario(db_path, accounts_base_url))


async def _remove_spectator_scenario(db_path, accounts_base_url):
    from kungfu_chess.server.game_room import BROADCAST_INTERVAL_SECONDS

    room = _make_room(db_path, accounts_base_url)
    await room.start()
    spectator_ws = FakeConnection("spectator")
    await room.add_spectator(spectator_ws)

    room.remove_spectator(spectator_ws)
    sent_count_after_removal = len(spectator_ws.sent)
    room._last_broadcast -= BROADCAST_INTERVAL_SECONDS
    await room._tick_once()

    assert len(spectator_ws.sent) == sent_count_after_removal  # no further sends once removed

    room.stop()


def test_spectator_survives_a_restart(db_path, accounts_base_url):
    """A RestartMessage rebuilds the game via _build_fresh_game - a
    spectator watching a room shouldn't have to rejoin after one."""
    asyncio.run(_spectator_survives_restart_scenario(db_path, accounts_base_url))


async def _spectator_survives_restart_scenario(db_path, accounts_base_url):
    room = _make_room(db_path, accounts_base_url)
    await room.start()
    spectator_ws = FakeConnection("spectator")
    await room.add_spectator(spectator_ws)

    room._build_fresh_game()

    assert spectator_ws in room._spectators


def test_match_found_message_carries_the_room_id_when_set(db_path, accounts_base_url):
    asyncio.run(_match_found_room_id_scenario(db_path, accounts_base_url))


async def _match_found_room_id_scenario(db_path, accounts_base_url):
    accounts.register(db_path, "white_player", "pw")
    accounts.register(db_path, "black_player", "pw")
    room = GameRoom(
        FakeConnection("white"), "white_player", FakeConnection("black"), "black_player",
        accounts_client=AccountsClient(accounts_base_url), room_id="ABC123",
    )

    assert (await room._match_found_message(WHITE)).room_id == "ABC123"


def test_match_found_message_room_id_is_none_for_a_play_matched_game(db_path, accounts_base_url):
    asyncio.run(_match_found_room_id_none_scenario(db_path, accounts_base_url))


async def _match_found_room_id_none_scenario(db_path, accounts_base_url):
    room = _make_room(db_path, accounts_base_url)

    assert (await room._match_found_message(WHITE)).room_id is None


def test_on_game_over_callback_does_not_fire_at_game_over_itself(db_path, accounts_base_url):
    """Both players might still click New Game in the same room - the
    room's own name in the registry must stay reserved for them until
    someone actually leaves, not free up the instant the game ends."""
    asyncio.run(_no_callback_at_game_over_scenario(db_path, accounts_base_url))


async def _no_callback_at_game_over_scenario(db_path, accounts_base_url):
    accounts.register(db_path, "white_player", "pw")
    accounts.register(db_path, "black_player", "pw")
    calls = []

    async def on_game_over():
        calls.append(1)

    room = GameRoom(
        FakeConnection("white"), "white_player", FakeConnection("black"), "black_player",
        accounts_client=AccountsClient(accounts_base_url), room_id="ABC123", on_game_over=on_game_over,
    )
    await room.start()

    view_state = _view_state_with_survivor(WHITE)
    await room._apply_rating_update(view_state)

    assert calls == []

    room.stop()


def test_on_game_over_callback_fires_exactly_once_when_a_player_leaves(db_path, accounts_base_url):
    asyncio.run(_on_game_over_callback_scenario(db_path, accounts_base_url))


async def _on_game_over_callback_scenario(db_path, accounts_base_url):
    accounts.register(db_path, "white_player", "pw")
    accounts.register(db_path, "black_player", "pw")
    calls = []

    async def on_game_over():
        calls.append(1)

    room = GameRoom(
        FakeConnection("white"), "white_player", FakeConnection("black"), "black_player",
        accounts_client=AccountsClient(accounts_base_url), room_id="ABC123", on_game_over=on_game_over,
    )
    await room.start()
    room._engine.resign()

    await room.leave(room._connections[WHITE])
    await room.leave(room._connections[WHITE])  # a second call (e.g. a raced disconnect) must not fire the callback again

    assert calls == [1]

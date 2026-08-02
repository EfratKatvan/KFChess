from __future__ import annotations

import asyncio
import uuid

import pytest
from websockets.asyncio.client import connect

from websockets.exceptions import ConnectionClosedOK

from kungfu_chess.model.piece import BLACK, WHITE
from kungfu_chess.server import accounts, protocol
from kungfu_chess.server.messages import (
    CreateRoomMessage,
    JoinRoomMessage,
    LeaveRoomMessage,
    LoginMessage,
    LogoutMessage,
    RegisterMessage,
    ResignMessage,
    SeekGameMessage,
    SelectOrMoveMessage,
    TokenLoginMessage,
)
from kungfu_chess.server.serialization import deserialize_message, serialize_message

"""End-to-end tests over real OS sockets (Server_Design.md sections
2/3/15, Stage 4a) - the one place that actually proves GameRoom runs
behind a genuine process boundary from the WS Gateway, not just that
the two sides' code compiles against each other. test_matchmaker.py
and test_game_shard.py test each side's own logic in isolation, with
fakes standing in for the other side; this file wires a real Shard, a
real WS Gateway, and real client sockets together."""


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test_users.db")
    accounts.init_db(path)
    return path


@pytest.fixture
def servers(shard_address, gateway_address):
    """Starts a real Shard + WS Gateway pair sharing one fresh Redis
    namespace, and returns the Gateway's (host, port) - the one address
    a real client ever needs to know about."""
    namespace = uuid.uuid4().hex
    shard_host, shard_port = shard_address(namespace)
    return gateway_address(namespace, shard_host, shard_port)


class RealClient:
    """A thin typed wrapper over a real websockets client connection.
    recv_type skips past unrelated messages (chiefly the periodic
    STATE broadcast) while waiting for a specific one - the same
    "doesn't matter what else arrives first" pattern a real client's
    own dispatch table already tolerates. `token` is stashed by _login
    (Stage 1b) so a test can drive a second connection's
    TokenLoginMessage without re-deriving it."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.token: str = ""

    async def send(self, message) -> None:
        await self.ws.send(serialize_message(message))

    async def recv(self):
        return deserialize_message(await self.ws.recv())

    async def recv_type(self, expected_type: str, timeout: float = 3.0):
        async def _until():
            while True:
                message = await self.recv()
                if message.type == expected_type:
                    return message

        return await asyncio.wait_for(_until(), timeout=timeout)


async def _login(host: str, port: int, username: str, register: bool = True) -> RealClient:
    ws = await connect(f"ws://{host}:{port}")
    client = RealClient(ws)
    if register:
        await client.send(RegisterMessage(username=username, password="pw"))
    else:
        await client.send(LoginMessage(username=username, password="pw"))
    login_ok = await client.recv_type(protocol.LOGIN_OK)
    client.token = login_ok.token
    return client


async def _login_with_token(host: str, port: int, username: str, token: str) -> RealClient:
    ws = await connect(f"ws://{host}:{port}")
    client = RealClient(ws)
    await client.send(TokenLoginMessage(token=token, username=username))
    return client


def test_a_full_match_move_and_resign_crosses_the_shard_process_boundary(db_path, accounts_base_url, servers):
    asyncio.run(_match_move_resign_scenario(servers))


async def _match_move_resign_scenario(servers):
    host, port = servers
    alice = await _login(host, port, "alice")
    bob = await _login(host, port, "bob")

    await alice.send(SeekGameMessage())
    await bob.send(SeekGameMessage())

    alice_matched = await alice.recv_type(protocol.MATCH_FOUND)
    bob_matched = await bob.recv_type(protocol.MATCH_FOUND)
    # Real, separate connections - unlike a single in-process test driving
    # both seeks sequentially, nothing guarantees which of two genuinely
    # concurrent seekers the server happens to process first, so either
    # could end up white. Only the pairing itself (opposite colors, same
    # room) is the actual guarantee worth asserting here.
    assert {alice_matched.color, bob_matched.color} == {WHITE, BLACK}
    assert alice_matched.room_id == bob_matched.room_id  # a real room_id, minted by Matchmaker, not a fake
    white = alice if alice_matched.color == WHITE else bob
    black = bob if white is alice else alice

    await white.send(SelectOrMoveMessage(row=6, col=0))  # select
    await white.send(SelectOrMoveMessage(row=5, col=0))  # move
    motion = await black.recv_type(protocol.PIECE_MOTION_STARTED)
    assert (motion.from_position.row, motion.from_position.col) == (6, 0)
    assert (motion.to_position.row, motion.to_position.col) == (5, 0)

    await white.send(ResignMessage())
    state = await black.recv_type(protocol.STATE)
    while not state.board.game_over:
        state = await black.recv_type(protocol.STATE)

    await alice.ws.close()
    await bob.ws.close()


def test_disconnect_and_reconnect_crosses_the_shard_process_boundary(db_path, accounts_base_url, servers):
    asyncio.run(_disconnect_reconnect_scenario(servers))


async def _disconnect_reconnect_scenario(servers):
    host, port = servers
    alice = await _login(host, port, "alice")
    bob = await _login(host, port, "bob")
    await alice.send(SeekGameMessage())
    await bob.send(SeekGameMessage())
    await alice.recv_type(protocol.MATCH_FOUND)
    await bob.recv_type(protocol.MATCH_FOUND)

    await alice.ws.close()  # alice's real socket drops mid-game
    await bob.recv_type(protocol.OPPONENT_DISCONNECTED)

    alice_new = await _login(host, port, "alice", register=False)
    await alice_new.recv_type(protocol.MATCH_FOUND)  # re-learns her own color/room
    await bob.recv_type(protocol.OPPONENT_RECONNECTED)

    await alice_new.ws.close()
    await bob.ws.close()


def test_reconnect_after_the_grace_period_falls_back_to_the_lobby(db_path, accounts_base_url, servers, monkeypatch):
    monkeypatch.setattr(protocol, "DISCONNECT_GRACE_SECONDS", 0.1)
    asyncio.run(_grace_expired_scenario(servers))


async def _grace_expired_scenario(servers):
    host, port = servers
    alice = await _login(host, port, "alice")
    bob = await _login(host, port, "bob")
    await alice.send(SeekGameMessage())
    await bob.send(SeekGameMessage())
    await alice.recv_type(protocol.MATCH_FOUND)
    await bob.recv_type(protocol.MATCH_FOUND)

    await alice.ws.close()
    await bob.recv_type(protocol.OPPONENT_DISCONNECTED)
    await asyncio.sleep(0.3)  # past the (shortened) grace period - the Shard has already auto-resigned

    alice_new = await _login(host, port, "alice", register=False)
    # The rejected reconnect attempt itself (Gateway opens a relay
    # session, the Shard finds the grace period already expired, closes
    # it with nothing sent - ws_gateway.py's mode-switching loop then
    # falls back to lobby mode) is silent by design, same as today's
    # single-process behavior - there's no positive signal to wait on,
    # only the *absence* of one. Sending the next message too eagerly
    # would race into that still-resolving relay session and be lost
    # (a real, narrow edge case worth naming - not exercised further
    # here); this in-memory-only round trip resolves near-instantly, so
    # a short buffer is enough without slowing the suite down.
    await asyncio.sleep(0.2)
    await alice_new.send(SeekGameMessage())
    # falls back to the lobby, same as a fresh login - no auto-matchmaking,
    # and no MATCH_FOUND ever arrives for the room that already moved on
    await alice_new.recv_type(protocol.WAITING_FOR_OPPONENT)

    await alice_new.ws.close()
    await bob.ws.close()


def test_room_create_join_spectate_and_leave_crosses_the_shard_process_boundary(db_path, accounts_base_url, servers):
    asyncio.run(_room_and_spectate_scenario(servers))


async def _room_and_spectate_scenario(servers):
    host, port = servers
    alice = await _login(host, port, "alice")
    bob = await _login(host, port, "bob")
    carol = await _login(host, port, "carol")

    await alice.send(CreateRoomMessage(room_id="efrat-room"))
    created = await alice.recv_type(protocol.ROOM_CREATED)
    room_id = created.room_id

    await bob.send(JoinRoomMessage(room_id=room_id))
    alice_matched = await alice.recv_type(protocol.MATCH_FOUND)
    bob_matched = await bob.recv_type(protocol.MATCH_FOUND)
    assert alice_matched.color == WHITE
    assert bob_matched.color == BLACK

    await carol.send(JoinRoomMessage(room_id=room_id))
    spectating = await carol.recv_type(protocol.SPECTATING)
    assert spectating.white_username == "alice"
    assert spectating.black_username == "bob"
    await carol.recv_type(protocol.STATE)  # the immediate snapshot add_spectator sends

    await alice.send(ResignMessage())
    state = await bob.recv_type(protocol.STATE)
    while not state.board.game_over:
        state = await bob.recv_type(protocol.STATE)

    await bob.send(LeaveRoomMessage())
    await bob.recv_type(protocol.LEFT_ROOM)
    await alice.recv_type(protocol.LEFT_ROOM)  # kicked back to the lobby too, per GameRoom.leave

    await alice.ws.close()
    await bob.ws.close()
    await carol.ws.close()


def test_logout_revokes_the_token_so_it_can_no_longer_log_back_in(db_path, accounts_base_url, servers):
    asyncio.run(_logout_revocation_scenario(servers))


async def _logout_revocation_scenario(servers):
    host, port = servers
    alice = await _login(host, port, "alice")
    token = alice.token

    await alice.send(LogoutMessage())
    await alice.recv_type(protocol.LOGGED_OUT)
    # matchmaker.py's _handle_logout closes with a normal code (1000) -
    # a clean close, not an error, is the whole point (see
    # network_transport.py: this is what lets the real client return to
    # the login screen instead of flashing "Disconnected").
    with pytest.raises(ConnectionClosedOK):
        await alice.ws.recv()

    alice_again = await _login_with_token(host, port, "alice", token)
    failed = await alice_again.recv_type(protocol.LOGIN_FAILED)
    assert "logged out" in failed.reason

    await alice_again.ws.close()


def test_a_valid_unrevoked_token_can_reconnect_with_the_current_rating(db_path, accounts_base_url, servers):
    asyncio.run(_token_login_positive_scenario(servers))


async def _token_login_positive_scenario(servers):
    host, port = servers
    alice = await _login(host, port, "alice")
    bob = await _login(host, port, "bob")
    token = alice.token

    # Play a game so alice's rating actually moves before she reconnects.
    await alice.send(SeekGameMessage())
    await bob.send(SeekGameMessage())
    alice_matched = await alice.recv_type(protocol.MATCH_FOUND)
    bob_matched = await bob.recv_type(protocol.MATCH_FOUND)
    white, black = (alice, bob) if alice_matched.color == WHITE else (bob, alice)
    await white.send(ResignMessage())
    state = await black.recv_type(protocol.STATE)
    while not state.board.game_over:
        state = await black.recv_type(protocol.STATE)
    await bob.ws.close()

    await alice.ws.close()  # not a logout - the token itself is still perfectly valid
    alice_new = await _login_with_token(host, port, "alice", token)
    login_ok = await alice_new.recv_type(protocol.LOGIN_OK)

    assert login_ok.username == "alice"
    # alice was white and resigned (or was black and won) - either way,
    # the returned rating must reflect that game, not the value from
    # when the token was first issued (see ws_gateway.py's _authenticate).
    assert login_ok.rating != accounts.STARTING_RATING

    await alice_new.ws.close()

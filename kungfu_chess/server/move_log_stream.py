from __future__ import annotations

import json
import os
import time
from typing import List, Tuple

import nats
from nats.js.errors import NotFoundError

from kungfu_chess.model.game_state import MoveLoggedEvent
from kungfu_chess.model.position import Position

# Env-overridable (Stage 5, section 17), same pattern as every other
# cross-process constant in this codebase.
NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")

# Server_Design.md section 3: a room's own stream only needs to outlive
# the room itself (games last 30-90s, section 9) - never an
# ever-growing dataset. Comfortably above the longest game, with room
# to spare for the replay itself to run.
STREAM_MAX_AGE_SECONDS = 90

"""The durable per-room move log crash recovery replays from
(Server_Design.md section 3, section 20.5) - NATS JetStream, not Redis
Pub/Sub, specifically because this is the one place in the whole
design that genuinely needs durability a plain pub/sub can't offer
(section 16.2): a message published while no one happens to be
subscribed (the exact situation right after a Shard crashes) must
still be there once a replacement reads it back.

Every accepted move is a small, self-contained record (see
MoveLoggedEvent) - published here the instant GameEngine.request_move
accepts it (see game_room.py's JetStreamMoveLogger observer), replayed
in full by whichever process rebuilds the room (game_shard.py's
_build_room, on finding existing history for a room_id instead of
starting fresh)."""


def _safe_name(room_id: str) -> str:
    """NATS subject/stream names disallow spaces, '.', '*', '>' and a
    few others - room_id is usually a uuid4 hex (already safe) or a
    player-typed Create Room name (not guaranteed to be), so this maps
    anything outside the safe set to '_' rather than trusting the
    input."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in room_id)


def _stream_name(room_id: str) -> str:
    return f"MOVES_{_safe_name(room_id)}"


def _subject(room_id: str) -> str:
    return f"moves.{_safe_name(room_id)}"


def _serialize(event: MoveLoggedEvent) -> bytes:
    return json.dumps(
        {
            "color": event.color,
            "from_row": event.from_pos.row,
            "from_col": event.from_pos.col,
            "to_row": event.to_pos.row,
            "to_col": event.to_pos.col,
            "kind": event.kind,
            "is_capture": event.is_capture,
            "elapsed_ms": event.elapsed_ms,
            "duration_ms": event.duration_ms,
            # Wall-clock, not game-time (elapsed_ms already is that) -
            # the one extra fact replay needs beyond the event itself:
            # how much *real* time has passed since the last recorded
            # move, to correctly fast-forward cooldowns past whatever
            # outage happened between the crash and this replay (see
            # game_room.py's GameRoom.replay).
            "published_at": time.time(),
        }
    ).encode("utf-8")


def _deserialize(data: bytes) -> Tuple[MoveLoggedEvent, float]:
    payload = json.loads(data)
    event = MoveLoggedEvent(
        color=payload["color"],
        from_pos=Position(payload["from_row"], payload["from_col"]),
        to_pos=Position(payload["to_row"], payload["to_col"]),
        kind=payload["kind"],
        is_capture=payload["is_capture"],
        elapsed_ms=payload["elapsed_ms"],
        duration_ms=payload["duration_ms"],
    )
    return event, payload["published_at"]


class MoveLogStream:
    """One connection, reused across every room this process ever
    hosts (a Game Shard's whole lifetime) - a fresh JetStream stream is
    created per room_id on that room's very first move, not up front,
    since most of a room's life (section 9: ~8.3 new rooms/sec/worker)
    is spent not yet knowing whether it'll need one at all until a
    move actually happens."""

    def __init__(self, nc, js) -> None:
        self._nc = nc
        self._js = js

    @classmethod
    async def connect(cls, url: str = NATS_URL) -> "MoveLogStream":
        nc = await nats.connect(url)
        return cls(nc, nc.jetstream())

    async def close(self) -> None:
        await self._nc.close()

    async def publish_move(self, room_id: str, event: MoveLoggedEvent) -> None:
        # add_stream is idempotent for an unchanged config (a plain
        # no-op update, not an error) - safe to call on every move
        # rather than tracking "have I already created this room's
        # stream" separately.
        await self._js.add_stream(
            name=_stream_name(room_id), subjects=[_subject(room_id)], max_age=STREAM_MAX_AGE_SECONDS
        )
        await self._js.publish(_subject(room_id), _serialize(event))

    async def replay_moves(self, room_id: str) -> List[Tuple[MoveLoggedEvent, float]]:
        """Every (move, wall-clock publish time) recorded for this room,
        in order - empty for a brand-new room (no stream created yet)
        or one whose retention window already lapsed (section 3's
        explicit trade-off: bounded retention, not indefinite storage)."""
        try:
            sub = await self._js.pull_subscribe(_subject(room_id), durable=None, stream=_stream_name(room_id))
        except NotFoundError:
            return []

        replayed: List[Tuple[MoveLoggedEvent, float]] = []
        while True:
            try:
                messages = await sub.fetch(100, timeout=1)
            except TimeoutError:
                break
            if not messages:
                break
            for message in messages:
                replayed.append(_deserialize(message.data))
                await message.ack()
        return replayed

    async def reset_room(self, room_id: str) -> None:
        """Discards this room's move history (Server_Design.md section
        3) - called when a room starts a genuinely new game in the same
        room_id (the "New Game"/RestartMessage rematch flow, see
        game_room.py's _handle_restart), so a later replay never mixes
        two different games' moves under one id. A no-op if this room
        never had a stream in the first place (nothing was ever
        replayed, or it already expired on its own)."""
        try:
            await self._js.delete_stream(_stream_name(room_id))
        except NotFoundError:
            pass

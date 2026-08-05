"""A real, reusable load-testing tool for the WS Gateway (Server_Design.md
section 9) - replaces the section's purely theoretical capacity estimates
with numbers actually measured against a running cluster.

Same style as the session's own scratch verification scripts
(k8s_matchmaking_check.py / k8s_shard_crash_check.py): plain asyncio +
websockets, no new dependency, driving real client connections through
register -> seek -> match -> a few moves -> disconnect. Unlike those
scripts, this one is checked in, generalized (configurable concurrency,
no hardcoded host/port), and reports percentile latencies instead of a
pass/fail assertion.

Usage:
    python tools/load_test.py --gateway-host localhost --gateway-port 8765 --pairs 20
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from websockets.asyncio.client import connect

from kungfu_chess.model.piece import WHITE
from kungfu_chess.server import protocol
from kungfu_chess.server.messages import RegisterMessage, SeekGameMessage, SelectOrMoveMessage
from kungfu_chess.server.serialization import deserialize_message, serialize_message


@dataclass
class PairResult:
    """One simulated player pair's timings, or the point where it failed."""

    login_seconds: List[float] = field(default_factory=list)
    match_seconds: Optional[float] = None
    move_round_trip_seconds: List[float] = field(default_factory=list)
    error: Optional[str] = None


async def _login(host: str, port: int, username: str) -> tuple:
    started = time.monotonic()
    ws = await connect(f"ws://{host}:{port}")
    await ws.send(serialize_message(RegisterMessage(username=username, password="pw")))
    while True:
        message = deserialize_message(await ws.recv())
        if message.type == protocol.LOGIN_OK:
            return ws, time.monotonic() - started
        if message.type == protocol.LOGIN_FAILED:
            raise RuntimeError(f"login failed for {username}: {message.reason}")


async def _recv_type(ws, expected_type: str, timeout: float):
    async def _until():
        while True:
            message = deserialize_message(await ws.recv())
            if message.type == expected_type:
                return message

    return await asyncio.wait_for(_until(), timeout=timeout)


async def _run_one_pair(host: str, port: int, pair_index: int, moves_per_pair: int, match_timeout: float) -> PairResult:
    result = PairResult()
    suffix = f"{uuid.uuid4().hex[:8]}_{pair_index}"
    white_ws = black_ws = None
    try:
        white_ws, white_login_s = await _login(host, port, f"loadtest_w_{suffix}")
        result.login_seconds.append(white_login_s)
        black_ws, black_login_s = await _login(host, port, f"loadtest_b_{suffix}")
        result.login_seconds.append(black_login_s)

        match_started = time.monotonic()
        await white_ws.send(serialize_message(SeekGameMessage()))
        await black_ws.send(serialize_message(SeekGameMessage()))
        white_match = await _recv_type(white_ws, protocol.MATCH_FOUND, match_timeout)
        await _recv_type(black_ws, protocol.MATCH_FOUND, match_timeout)
        result.match_seconds = time.monotonic() - match_started

        white_client = white_ws if white_match.color == WHITE else black_ws
        black_client = black_ws if white_match.color == WHITE else white_ws
        # Alternates seats so both connections take a turn selecting one of
        # their own pawns (row 6 for White, row 1 for Black per
        # kungfu_chess.starting_position.STARTING_POSITION) and waiting for
        # the resulting personal STATE reply (game_room.py's
        # _handle_select_or_move sends one immediately whenever a selection
        # actually changes) - a real client round-trip, not a legal-move
        # sequence (no moves are ever completed, just repeated selections).
        movers = [(white_client, 6), (black_client, 1)]
        for i in range(moves_per_pair):
            mover, row = movers[i % 2]
            move_started = time.monotonic()
            await mover.send(serialize_message(SelectOrMoveMessage(row=row, col=i % 8)))
            await _recv_type(mover, protocol.STATE, timeout=5.0)
            result.move_round_trip_seconds.append(time.monotonic() - move_started)
    except Exception as error:  # noqa: BLE001 - a failed simulated pair is a data point, not a crash
        result.error = f"{type(error).__name__}: {error}"
    finally:
        for ws in (white_ws, black_ws):
            if ws is not None:
                await ws.close()
    return result


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * pct))
    return ordered[index]


def _report(label: str, values: List[float]) -> None:
    if not values:
        print(f"  {label}: no samples")
        return
    print(
        f"  {label}: n={len(values)} "
        f"p50={_percentile(values, 0.50) * 1000:.1f}ms "
        f"p95={_percentile(values, 0.95) * 1000:.1f}ms "
        f"p99={_percentile(values, 0.99) * 1000:.1f}ms "
        f"mean={statistics.mean(values) * 1000:.1f}ms"
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-host", default="localhost")
    parser.add_argument("--gateway-port", type=int, default=8765)
    parser.add_argument("--pairs", type=int, default=10, help="number of concurrent simulated player pairs")
    parser.add_argument("--moves-per-pair", type=int, default=4)
    parser.add_argument("--ramp-up-seconds", type=float, default=0.0, help="spread pair starts over this many seconds")
    parser.add_argument("--match-timeout", type=float, default=15.0)
    parser.add_argument("--json-out", default=None, help="optional path to dump raw results as JSON")
    args = parser.parse_args()

    async def _delayed(i: int):
        if args.ramp_up_seconds and args.pairs > 1:
            await asyncio.sleep(args.ramp_up_seconds * i / (args.pairs - 1))
        return await _run_one_pair(args.gateway_host, args.gateway_port, i, args.moves_per_pair, args.match_timeout)

    print(f"Running {args.pairs} simulated player pairs against ws://{args.gateway_host}:{args.gateway_port} ...")
    started = time.monotonic()
    results = await asyncio.gather(*(_delayed(i) for i in range(args.pairs)))
    total_seconds = time.monotonic() - started

    failures = [r for r in results if r.error is not None]
    successes = [r for r in results if r.error is None]

    login_seconds = [s for r in results for s in r.login_seconds]
    match_seconds = [r.match_seconds for r in successes if r.match_seconds is not None]
    move_seconds = [s for r in successes for s in r.move_round_trip_seconds]

    print(f"\n=== Load test report ({args.pairs} pairs, {total_seconds:.1f}s wall clock) ===")
    print(f"  pairs succeeded: {len(successes)}/{args.pairs}  pairs failed: {len(failures)}")
    _report("login latency", login_seconds)
    _report("time-to-match latency", match_seconds)
    _report("move round-trip latency", move_seconds)
    if failures:
        print("\n  sample failures:")
        for r in failures[:5]:
            print(f"    - {r.error}")

    if args.json_out:
        payload = {
            "pairs": args.pairs,
            "wall_clock_seconds": total_seconds,
            "succeeded": len(successes),
            "failed": len(failures),
            "login_seconds": login_seconds,
            "match_seconds": match_seconds,
            "move_round_trip_seconds": move_seconds,
            "failures": [r.error for r in failures],
        }
        Path(args.json_out).write_text(json.dumps(payload, indent=2))
        print(f"\n  raw results written to {args.json_out}")


if __name__ == "__main__":
    asyncio.run(main())

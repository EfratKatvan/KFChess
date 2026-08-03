from __future__ import annotations

import os

from prometheus_client import start_http_server

# Env-overridable (Stage 5, section 17), same pattern as every other
# cross-process constant - one port, reused by every role, since each
# runs in its own container with its own network namespace (no
# collision the way there would be sharing one host process).
METRICS_PORT = int(os.environ.get("METRICS_PORT", "9100"))

"""Server_Design.md section 1's "Observability" row / Stage 6:
Prometheus, not a bespoke logging pipeline - each role exposes its own
`/metrics` on METRICS_PORT via prometheus_client's own tiny built-in
HTTP server (no aiohttp route needed, and no extra dependency for the
two roles - ws_gateway.py, game_shard.py - that aren't HTTP servers at
all). Also doubles as the health check every role's docker-compose.yml
entry uses (`GET /metrics` returning 200 - a process that can report
its own metrics is, by construction, alive and its event loop is
responsive) - one mechanism for both concerns, not two.

What each role actually measures is deliberately the same signal
Server_Design.md section 1's own table already names as that role's
scaling metric - request rate (API Service), open connections (WS
Gateway), queue depth (Matchmaking Service), active-room count (Game
Shard) - not a generic, undifferentiated pile of counters."""


def start_metrics_server(port: int = METRICS_PORT) -> None:
    start_http_server(port)

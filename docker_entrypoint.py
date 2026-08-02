# Git repo: https://github.com/EfratKatvan/KFChess.git
from __future__ import annotations

import importlib
import os
import sys

"""Docker entrypoint (Stage 5, Server_Design.md section 17, strategy B):
one image, the actual role picked at container-start by SERVICE_ROLE -
the same one-line "import main, call it" shape as server.py/shard.py/
api.py/matchmaking.py, just choosing which of those four modules based
on an env var instead of always the same one. All 4 of the design's
logical units are now separate processes (Matchmaker's own network
transport - matchmaking_service.py - closed the gap Server_Design.md
section 19's Stage 5 note originally flagged)."""

_ROLES = {
    "api": "kungfu_chess.server.accounts_service",
    "ws-gateway": "kungfu_chess.server.ws_gateway",
    "game-shard": "kungfu_chess.server.game_shard",
    "matchmaking": "kungfu_chess.server.matchmaking_service",
}


def main() -> None:
    role = os.environ.get("SERVICE_ROLE")
    module_name = _ROLES.get(role)
    if module_name is None:
        sys.exit(f"SERVICE_ROLE must be one of {sorted(_ROLES)}, got {role!r}")
    importlib.import_module(module_name).main()


if __name__ == "__main__":
    main()

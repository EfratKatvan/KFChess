# Git repo: https://github.com/EfratKatvan/KFChess.git
from __future__ import annotations

import importlib
import os
import sys

"""Docker entrypoint (Stage 5, Server_Design.md section 17, strategy B):
one image, the actual role picked at container-start by SERVICE_ROLE -
the same one-line "import main, call it" shape as server.py/shard.py/
api.py, just choosing which of those three modules based on an env var
instead of always the same one. Only 3 roles exist because only 3 of
the design's 4 logical units are actually separate processes today -
Matchmaker still runs in-process inside ws_gateway.py (see
Server_Design.md section 19's Stage 5 note); there is no standalone
Matchmaking Service process yet to give a 4th role to."""

_ROLES = {
    "api": "kungfu_chess.server.accounts_service",
    "ws-gateway": "kungfu_chess.server.ws_gateway",
    "game-shard": "kungfu_chess.server.game_shard",
}


def main() -> None:
    role = os.environ.get("SERVICE_ROLE")
    module_name = _ROLES.get(role)
    if module_name is None:
        sys.exit(f"SERVICE_ROLE must be one of {sorted(_ROLES)}, got {role!r}")
    importlib.import_module(module_name).main()


if __name__ == "__main__":
    main()

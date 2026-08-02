from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Tuple

"""Local persistence for a saved login session (Stage 1b,
Server_Design.md section 1.1) - lets the login screen offer "Continue
as X" using a previously-issued token instead of retyping a password
(see client/network_transport.py, which calls save_token/clear_token
as a side effect of LoginOkMessage/LoggedOutMessage, the same way it
already treats sound playback as its one non-drawing side effect).
Deliberately a single file, not per-username: a fresh login for a
different account naturally overwrites whatever was saved before, with
no extra "switch account" UI needed."""

_SESSION_FILE = Path(".kfchess_session.json")


def save_token(username: str, token: str) -> None:
    _SESSION_FILE.write_text(json.dumps({"username": username, "token": token}))


def load_token() -> Optional[Tuple[str, str]]:
    """None for anything wrong with the file - missing, unreadable,
    corrupted, or simply not shaped as expected. This runs on every
    app launch before any connection exists; a broken save file must
    never block reaching the login screen."""
    try:
        data = json.loads(_SESSION_FILE.read_text())
        return data["username"], data["token"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None


def clear_token() -> None:
    try:
        _SESSION_FILE.unlink()
    except OSError:
        pass

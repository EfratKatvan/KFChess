from __future__ import annotations

import logging

"""One place both entrypoints (server/server.py's main(), and the
client's app.py) call once at startup - not imported by anything else,
so every module can just do logging.getLogger(__name__) and trust the
root logger's handlers (set up here) to route it correctly."""


def configure_logging(log_file: str, console_level: int = logging.INFO, file_level: int = logging.DEBUG) -> None:
    """One FileHandler (everything, including per-message DEBUG wire
    traffic - see server/serialization.py) and one StreamHandler
    (INFO+ narrative only, so the up-to-15/sec StateMessage broadcast
    never floods the terminal). Idempotent - a second call is a no-op,
    so it's safe to call from a test without accumulating duplicate
    handlers across the process."""
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

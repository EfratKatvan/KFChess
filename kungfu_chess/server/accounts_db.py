from __future__ import annotations

import sqlite3
from typing import Optional, Tuple

DEFAULT_DB_PATH = "kfchess_users.db"

"""The accounts persistence layer: every sqlite3.connect/execute for the
users table lives here, and only here - no password hashing, no ELO
math, no login/registration decisions. accounts.py (the application
layer) is the only caller; it owns all of that logic and treats this
module as a plain key-value store it happens to keep on disk."""


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                rating INTEGER NOT NULL DEFAULT 1200
            )
            """
        )


def fetch_user(db_path: str, username: str) -> Optional[Tuple[str, str, int]]:
    """(salt, password_hash, rating) for an existing username, or None."""
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT salt, password_hash, rating FROM users WHERE username = ?", (username,)
        ).fetchone()
    return row


def insert_user(db_path: str, username: str, salt: str, password_hash: str, rating: int) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO users (username, salt, password_hash, rating) VALUES (?, ?, ?, ?)",
            (username, salt, password_hash, rating),
        )


def fetch_rating(db_path: str, username: str) -> Optional[int]:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT rating FROM users WHERE username = ?", (username,)).fetchone()
    return row[0] if row is not None else None


def fetch_ratings(db_path: str, first_username: str, second_username: str) -> Tuple[int, int]:
    """Both ratings in one connection - a complex-query convenience for
    callers (e.g. an ELO update) that need a consistent pair of reads,
    not a place for business logic."""
    with sqlite3.connect(db_path) as connection:
        first_rating = connection.execute(
            "SELECT rating FROM users WHERE username = ?", (first_username,)
        ).fetchone()[0]
        second_rating = connection.execute(
            "SELECT rating FROM users WHERE username = ?", (second_username,)
        ).fetchone()[0]
    return first_rating, second_rating


def write_ratings(db_path: str, first_username: str, first_rating: int, second_username: str, second_rating: int) -> None:
    """Both writes in one connection, mirroring fetch_ratings above."""
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE users SET rating = ? WHERE username = ?", (first_rating, first_username))
        connection.execute("UPDATE users SET rating = ? WHERE username = ?", (second_rating, second_username))

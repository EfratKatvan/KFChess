from __future__ import annotations

import os
from typing import Optional, Tuple

import psycopg2
from psycopg2 import sql

# Env-overridable (Server_Design.md section 6, Stage 5's section 17
# pattern): a single, network-reachable, replicated Postgres instead of
# a local SQLite file - the fix section 6 argued for (SQLite's real
# problem was never row count, it was being a single-writer file with
# no network protocol, unshareable across the many Accounts-Service-
# adjacent processes/machines this design otherwise assumes).
POSTGRES_DSN = os.environ.get("POSTGRES_DSN", "postgresql://kfchess:kfchess@localhost:5432/kfchess")

# Every table lives inside a schema, not always "public" - production
# always uses DEFAULT_SCHEMA; tests get their own throwaway schema
# (see tests/unit/conftest.py's db_path fixture) for the same reason a
# throwaway SQLite file used to serve: real isolation between
# concurrently-running tests, without one test's data ever leaking
# into another's uniqueness constraints.
DEFAULT_SCHEMA = "public"

"""The accounts persistence layer: every psycopg2 connect/execute for
the users table lives here, and only here - no password hashing, no
ELO math, no login/registration decisions. accounts.py (the
application layer) is the only caller; it owns all of that logic and
treats this module as a plain key-value store it happens to keep in
Postgres. A fresh connection per call, deliberately - the same
simplicity level the old sqlite3.connect(db_path)-per-call code already
had; connection pooling is a real optimization but a separate concern
from *which* database this talks to, not part of this migration."""


def _connect(schema: str):
    connection = psycopg2.connect(POSTGRES_DSN)
    connection.cursor().execute(
        sql.SQL("SET search_path TO {}").format(sql.Identifier(schema))
    )
    return connection


def init_db(schema: str = DEFAULT_SCHEMA) -> None:
    with _connect(schema) as connection:
        with connection.cursor() as cursor:
            if schema != "public":
                cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    rating INTEGER NOT NULL DEFAULT 1200
                )
                """
            )


def drop_schema(schema: str) -> None:
    """Test-only teardown (see conftest.py's db_path fixture) - never
    called for DEFAULT_SCHEMA ("public" is never dropped)."""
    assert schema != "public", "refusing to drop the public schema"
    with _connect(DEFAULT_SCHEMA) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


def fetch_user(schema: str, username: str) -> Optional[Tuple[str, str, int]]:
    """(salt, password_hash, rating) for an existing username, or None."""
    with _connect(schema) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT salt, password_hash, rating FROM users WHERE username = %s", (username,))
            return cursor.fetchone()


def insert_user(schema: str, username: str, salt: str, password_hash: str, rating: int) -> None:
    with _connect(schema) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (username, salt, password_hash, rating) VALUES (%s, %s, %s, %s)",
                (username, salt, password_hash, rating),
            )


def fetch_rating(schema: str, username: str) -> Optional[int]:
    with _connect(schema) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT rating FROM users WHERE username = %s", (username,))
            row = cursor.fetchone()
    return row[0] if row is not None else None


def fetch_ratings(schema: str, first_username: str, second_username: str) -> Tuple[int, int]:
    """Both ratings in one connection - a complex-query convenience for
    callers (e.g. an ELO update) that need a consistent pair of reads,
    not a place for business logic."""
    with _connect(schema) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT rating FROM users WHERE username = %s", (first_username,))
            first_rating = cursor.fetchone()[0]
            cursor.execute("SELECT rating FROM users WHERE username = %s", (second_username,))
            second_rating = cursor.fetchone()[0]
    return first_rating, second_rating


def write_ratings(schema: str, first_username: str, first_rating: int, second_username: str, second_rating: int) -> None:
    """Both writes in one connection, mirroring fetch_ratings above."""
    with _connect(schema) as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE users SET rating = %s WHERE username = %s", (first_rating, first_username))
            cursor.execute("UPDATE users SET rating = %s WHERE username = %s", (second_rating, second_username))

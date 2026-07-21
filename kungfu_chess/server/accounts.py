from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass
from typing import Optional, Tuple

DEFAULT_DB_PATH = "kfchess_users.db"
STARTING_RATING = 1200
ELO_K_FACTOR = 32

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthResult:
    """success + rating on a good login/registration; reason set only on
    failure (wrong password for an existing username)."""

    success: bool
    rating: Optional[int] = None
    reason: Optional[str] = None


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                rating INTEGER NOT NULL DEFAULT 1200
            )
            """
        )


def authenticate(db_path: str, username: str, password: str) -> AuthResult:
    """First login for a username registers it (with this password, at
    STARTING_RATING) - every login after that must match the same
    password already stored."""
    password_hash = _hash_password(password)
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT password_hash, rating FROM users WHERE username = ?", (username,)
        ).fetchone()

        if row is None:
            connection.execute(
                "INSERT INTO users (username, password_hash, rating) VALUES (?, ?, ?)",
                (username, password_hash, STARTING_RATING),
            )
            logger.info("login ok: %s (new account)", username)
            return AuthResult(success=True, rating=STARTING_RATING)

        stored_hash, rating = row
        if stored_hash != password_hash:
            logger.info("login failed: %s (wrong password)", username)
            return AuthResult(success=False, reason="wrong password")
        logger.info("login ok: %s", username)
        return AuthResult(success=True, rating=rating)


def get_rating(db_path: str, username: str) -> Optional[int]:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT rating FROM users WHERE username = ?", (username,)).fetchone()
        return row[0] if row is not None else None


def expected_score(rating: int, opponent_rating: int) -> float:
    """Standard ELO expected-score formula - the probability rating is
    predicted to score against opponent_rating (1.0 = certain win)."""
    return 1.0 / (1.0 + 10 ** ((opponent_rating - rating) / 400))


def update_ratings_after_game(
    db_path: str, winner_username: str, loser_username: str, k_factor: int = ELO_K_FACTOR
) -> Tuple[int, int]:
    """Applies one ELO update for a decisive (no-draw) game - the
    smaller the winner's expected score was going in (i.e. the bigger
    the upset), the more rating moves. Returns (new_winner_rating,
    new_loser_rating)."""
    with sqlite3.connect(db_path) as connection:
        winner_rating = connection.execute(
            "SELECT rating FROM users WHERE username = ?", (winner_username,)
        ).fetchone()[0]
        loser_rating = connection.execute(
            "SELECT rating FROM users WHERE username = ?", (loser_username,)
        ).fetchone()[0]

        winner_expected = expected_score(winner_rating, loser_rating)
        loser_expected = expected_score(loser_rating, winner_rating)

        new_winner_rating = round(winner_rating + k_factor * (1 - winner_expected))
        new_loser_rating = round(loser_rating + k_factor * (0 - loser_expected))

        connection.execute("UPDATE users SET rating = ? WHERE username = ?", (new_winner_rating, winner_username))
        connection.execute("UPDATE users SET rating = ? WHERE username = ?", (new_loser_rating, loser_username))

        return new_winner_rating, new_loser_rating

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Optional, Tuple

from kungfu_chess.server import accounts_db
from kungfu_chess.server.accounts_db import DEFAULT_DB_PATH

STARTING_RATING = 1200
ELO_K_FACTOR = 32

logger = logging.getLogger(__name__)

"""The accounts application layer: password hashing, the
login-vs-register decision, and the ELO math - all business logic, none
of it touching sqlite3 directly (see accounts_db.py for that). Callers
across the server (server.py, matchmaker.py, game_room.py) only ever
import this module, never accounts_db directly."""


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
    accounts_db.init_db(db_path)


def login(db_path: str, username: str, password: str) -> AuthResult:
    """Only succeeds for an already-registered username with the right
    password - unlike the old auto-register-on-first-login behavior,
    an unknown username is now a rejection, not a fresh account (see
    register() for that)."""
    existing = accounts_db.fetch_user(db_path, username)
    if existing is None:
        logger.info("login failed: %s (no such account)", username)
        return AuthResult(success=False, reason="no such account - please register")

    stored_hash, rating = existing
    if stored_hash != _hash_password(password):
        logger.info("login failed: %s (wrong password)", username)
        return AuthResult(success=False, reason="wrong password")
    logger.info("login ok: %s", username)
    return AuthResult(success=True, rating=rating)


def register(db_path: str, username: str, password: str) -> AuthResult:
    """Only succeeds for a username that doesn't exist yet, creating it
    at STARTING_RATING - the login()-equivalent counterpart for a
    username that's already taken is a rejection, not a silent
    password check."""
    if accounts_db.fetch_user(db_path, username) is not None:
        logger.info("register failed: %s (username already taken)", username)
        return AuthResult(success=False, reason="username already taken")

    accounts_db.insert_user(db_path, username, _hash_password(password), STARTING_RATING)
    logger.info("register ok: %s (new account)", username)
    return AuthResult(success=True, rating=STARTING_RATING)


def get_rating(db_path: str, username: str) -> Optional[int]:
    return accounts_db.fetch_rating(db_path, username)


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
    new_loser_rating). All the math is here; accounts_db only supplies
    the before/after numbers."""
    winner_rating, loser_rating = accounts_db.fetch_ratings(db_path, winner_username, loser_username)

    winner_expected = expected_score(winner_rating, loser_rating)
    loser_expected = expected_score(loser_rating, winner_rating)

    new_winner_rating = round(winner_rating + k_factor * (1 - winner_expected))
    new_loser_rating = round(loser_rating + k_factor * (0 - loser_expected))

    accounts_db.write_ratings(db_path, winner_username, new_winner_rating, loser_username, new_loser_rating)
    return new_winner_rating, new_loser_rating

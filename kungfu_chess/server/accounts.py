from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from typing import Optional, Tuple

from kungfu_chess.server import accounts_db, auth_token
from kungfu_chess.server.accounts_db import DEFAULT_SCHEMA

STARTING_RATING = 1200
ELO_K_FACTOR = 32
PBKDF2_ITERATIONS = 200_000  # matches OWASP's current minimum recommendation for PBKDF2-HMAC-SHA256

logger = logging.getLogger(__name__)

"""The accounts application layer: password hashing, the
login-vs-register decision, and the ELO math - all business logic, none
of it touching Postgres directly (see accounts_db.py for that -
Server_Design.md section 6: a replicated, network-reachable Postgres,
not the single-writer local SQLite file this used to be). Since Stage 1
(Server_Design.md section 19), accounts_service.py is the only process
that actually calls into this module's DB-backed functions; ws_gateway.py
imports it only for the pure AuthResult type, and matchmaker.py/
game_room.py reach accounts over HTTP via accounts_client.AccountsClient
instead. `schema` names which Postgres schema each call operates in -
always DEFAULT_SCHEMA ("public") in production, a fresh throwaway one
per test (see tests/unit/conftest.py's db_path fixture)."""


@dataclass(frozen=True)
class AuthResult:
    """success + rating + a signed session token on a good
    login/registration (Server_Design.md section 1.1, Stage 1b) - reason
    set only on failure (wrong password for an existing username)."""

    success: bool
    rating: Optional[int] = None
    reason: Optional[str] = None
    token: Optional[str] = None


def _hash_password(password: str, salt: str) -> str:
    """Salted + stretched (PBKDF2-HMAC-SHA256, 200k iterations) rather
    than a single plain SHA-256 pass - an unsalted single hash is
    crackable via a precomputed rainbow table, and fast enough per
    guess for GPU brute-forcing regardless of the actual password's
    strength. A random salt per user (see register()) means even two
    accounts with the same password get different stored hashes."""
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS).hex()


def init_db(schema: str = DEFAULT_SCHEMA) -> None:
    accounts_db.init_db(schema)


def login(schema: str, username: str, password: str) -> AuthResult:
    """Only succeeds for an already-registered username with the right
    password - unlike the old auto-register-on-first-login behavior,
    an unknown username is now a rejection, not a fresh account (see
    register() for that)."""
    existing = accounts_db.fetch_user(schema, username)
    if existing is None:
        logger.info("login failed: %s (no such account)", username)
        return AuthResult(success=False, reason="no such account - please register")

    salt, stored_hash, rating = existing
    # Constant-time comparison - a plain != would let an attacker who
    # can measure response time narrow down the correct hash one byte
    # at a time (the comparison would return sooner on an early
    # mismatch than a late one).
    if not hmac.compare_digest(_hash_password(password, salt), stored_hash):
        logger.info("login failed: %s (wrong password)", username)
        return AuthResult(success=False, reason="wrong password")
    logger.info("login ok: %s", username)
    return AuthResult(success=True, rating=rating, token=auth_token.issue_token(username, rating))


def register(schema: str, username: str, password: str) -> AuthResult:
    """Only succeeds for a username that doesn't exist yet, creating it
    at STARTING_RATING - the login()-equivalent counterpart for a
    username that's already taken is a rejection, not a silent
    password check."""
    if accounts_db.fetch_user(schema, username) is not None:
        logger.info("register failed: %s (username already taken)", username)
        return AuthResult(success=False, reason="username already taken")

    salt = secrets.token_hex(16)
    accounts_db.insert_user(schema, username, salt, _hash_password(password, salt), STARTING_RATING)
    logger.info("register ok: %s (new account)", username)
    return AuthResult(success=True, rating=STARTING_RATING, token=auth_token.issue_token(username, STARTING_RATING))


def get_rating(schema: str, username: str) -> Optional[int]:
    return accounts_db.fetch_rating(schema, username)


def expected_score(rating: int, opponent_rating: int) -> float:
    """Standard ELO expected-score formula - the probability rating is
    predicted to score against opponent_rating (1.0 = certain win)."""
    return 1.0 / (1.0 + 10 ** ((opponent_rating - rating) / 400))


def update_ratings_after_game(
    schema: str, winner_username: str, loser_username: str, k_factor: int = ELO_K_FACTOR
) -> Tuple[int, int]:
    """Applies one ELO update for a decisive (no-draw) game - the
    smaller the winner's expected score was going in (i.e. the bigger
    the upset), the more rating moves. Returns (new_winner_rating,
    new_loser_rating). All the math is here; accounts_db only supplies
    the before/after numbers."""
    winner_rating, loser_rating = accounts_db.fetch_ratings(schema, winner_username, loser_username)

    winner_expected = expected_score(winner_rating, loser_rating)
    loser_expected = expected_score(loser_rating, winner_rating)

    new_winner_rating = round(winner_rating + k_factor * (1 - winner_expected))
    new_loser_rating = round(loser_rating + k_factor * (0 - loser_expected))

    accounts_db.write_ratings(schema, winner_username, new_winner_rating, loser_username, new_loser_rating)
    return new_winner_rating, new_loser_rating

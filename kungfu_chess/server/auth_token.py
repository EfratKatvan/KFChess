from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Optional

import jwt

"""JWT issuance/verification (Server_Design.md section 1.1, Stage 1b) -
pure logic, no I/O, no Redis: the same ports-and-adapters split
shard_protocol.py already uses (a plain function here, wrapped by
whatever transport/storage layer needs it - accounts.py issues,
ws_gateway.py verifies). Revocation itself lives in Redis, checked by
the caller (ws_gateway.py) - this module only ever proves "was this
signed by us, and hasn't expired," never "has it been revoked since.\""""

SECRET_KEY = "kfchess-dev-secret-change-in-production"  # hardcoded, matching every other cross-process constant in this codebase (REDIS_HOST, ACCOUNTS_SERVICE_URL, SHARD_HOST) - a real deployment would pull this from a secret store, not source control
ALGORITHM = "HS256"
TOKEN_TTL_SECONDS = 3600


@dataclass(frozen=True)
class TokenClaims:
    """Everything a Gateway needs from a verified token, without ever
    going back to the Accounts DB - username/rating for display, jti
    for revocation lookups, expires_at so a caller can compute how long
    a revocation entry needs to live (see matchmaker.py's _handle_logout)."""

    username: str
    rating: int
    jti: str
    expires_at: int  # unix timestamp


def issue_token(username: str, rating: int) -> str:
    now = int(time.time())
    payload = {
        "sub": username,
        "rating": rating,
        "iat": now,
        "exp": now + TOKEN_TTL_SECONDS,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> Optional[TokenClaims]:
    """None for anything wrong with the token itself - a bad signature,
    a tampered payload, or one that's simply expired (jwt.decode raises
    for all three, distinctly, but the caller never needs to tell them
    apart: any of them means "log in again"). algorithms is always
    passed explicitly - never omit it, or a token signed with an
    attacker-chosen algorithm could be accepted."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    return TokenClaims(
        username=payload["sub"], rating=payload["rating"], jti=payload["jti"], expires_at=payload["exp"]
    )

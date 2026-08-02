import jwt

from kungfu_chess.server import auth_token


def test_issue_then_verify_round_trips_the_claims():
    token = auth_token.issue_token("alice", 1200)

    claims = auth_token.verify_token(token)

    assert claims.username == "alice"
    assert claims.rating == 1200
    assert claims.jti  # a real unique id, not blank
    assert claims.expires_at > 0


def test_two_tokens_for_the_same_user_get_different_jtis():
    """Each login issues its own token, independently revocable - two
    concurrent sessions for one user must never share a jti, or logging
    out one would silently revoke the other too."""
    first = auth_token.verify_token(auth_token.issue_token("alice", 1200))
    second = auth_token.verify_token(auth_token.issue_token("alice", 1200))

    assert first.jti != second.jti


def test_verify_token_rejects_garbage():
    assert auth_token.verify_token("not a real token") is None


def test_verify_token_rejects_an_expired_token(monkeypatch):
    monkeypatch.setattr(auth_token, "TOKEN_TTL_SECONDS", -1)  # already expired the instant it's issued

    token = auth_token.issue_token("alice", 1200)

    assert auth_token.verify_token(token) is None


def test_verify_token_rejects_a_token_signed_with_a_different_key():
    payload = {"sub": "alice", "rating": 1200, "iat": 0, "exp": 9999999999, "jti": "x"}
    tampered = jwt.encode(payload, "a-different-secret", algorithm=auth_token.ALGORITHM)

    assert auth_token.verify_token(tampered) is None


def test_verify_token_rejects_a_token_signed_with_a_different_algorithm():
    """PyJWT's classic footgun: omitting `algorithms=` from jwt.decode
    can let a token claim any algorithm it likes, including "none". A
    token that's otherwise validly signed but under a different
    algorithm than auth_token.ALGORITHM must still be rejected."""
    payload = {"sub": "alice", "rating": 1200, "iat": 0, "exp": 9999999999, "jti": "x"}
    other_algorithm = jwt.encode(payload, auth_token.SECRET_KEY, algorithm="HS512")

    assert auth_token.verify_token(other_algorithm) is None

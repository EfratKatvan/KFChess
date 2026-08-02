from kungfu_chess.client import token_store


def test_load_token_with_no_saved_session_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(token_store, "_SESSION_FILE", tmp_path / ".kfchess_session.json")

    assert token_store.load_token() is None


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(token_store, "_SESSION_FILE", tmp_path / ".kfchess_session.json")

    token_store.save_token("efrat", "a-jwt-token")

    assert token_store.load_token() == ("efrat", "a-jwt-token")


def test_a_fresh_login_overwrites_the_previously_saved_session(tmp_path, monkeypatch):
    """One file, not per-username - a login for a different account
    naturally replaces whatever was saved before, with no separate
    "switch account" UI needed."""
    monkeypatch.setattr(token_store, "_SESSION_FILE", tmp_path / ".kfchess_session.json")
    token_store.save_token("alice", "alice-token")

    token_store.save_token("bob", "bob-token")

    assert token_store.load_token() == ("bob", "bob-token")


def test_clear_token_removes_the_saved_session(tmp_path, monkeypatch):
    monkeypatch.setattr(token_store, "_SESSION_FILE", tmp_path / ".kfchess_session.json")
    token_store.save_token("efrat", "a-jwt-token")

    token_store.clear_token()

    assert token_store.load_token() is None


def test_clear_token_with_nothing_saved_is_a_no_op(tmp_path, monkeypatch):
    monkeypatch.setattr(token_store, "_SESSION_FILE", tmp_path / ".kfchess_session.json")

    token_store.clear_token()  # must not raise


def test_load_token_fails_open_on_a_corrupted_file(tmp_path, monkeypatch):
    """Runs on every app launch before any connection exists - a
    hand-edited or half-written file must never crash the client
    before it even reaches the login screen."""
    session_file = tmp_path / ".kfchess_session.json"
    session_file.write_text("not json at all")
    monkeypatch.setattr(token_store, "_SESSION_FILE", session_file)

    assert token_store.load_token() is None


def test_load_token_fails_open_when_the_saved_json_is_missing_expected_fields(tmp_path, monkeypatch):
    session_file = tmp_path / ".kfchess_session.json"
    session_file.write_text('{"unexpected": "shape"}')
    monkeypatch.setattr(token_store, "_SESSION_FILE", session_file)

    assert token_store.load_token() is None

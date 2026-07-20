import sqlite3

import pytest

from kungfu_chess.server import accounts


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test_users.db")
    accounts.init_db(path)
    return path


def test_first_login_registers_the_username_at_the_starting_rating(db_path):
    result = accounts.authenticate(db_path, "efrat", "hunter2")
    assert result.success is True
    assert result.rating == accounts.STARTING_RATING


def test_second_login_with_the_same_password_succeeds(db_path):
    accounts.authenticate(db_path, "efrat", "hunter2")
    result = accounts.authenticate(db_path, "efrat", "hunter2")
    assert result.success is True
    assert result.rating == accounts.STARTING_RATING


def test_second_login_with_a_different_password_fails(db_path):
    accounts.authenticate(db_path, "efrat", "hunter2")
    result = accounts.authenticate(db_path, "efrat", "wrong-password")
    assert result.success is False
    assert result.reason is not None


def test_password_is_not_stored_in_plain_text(db_path):
    accounts.authenticate(db_path, "efrat", "hunter2")
    with sqlite3.connect(db_path) as connection:
        stored = connection.execute("SELECT password_hash FROM users WHERE username = ?", ("efrat",)).fetchone()[0]
    assert stored != "hunter2"


def test_get_rating_returns_none_for_an_unknown_username(db_path):
    assert accounts.get_rating(db_path, "nobody") is None


def test_get_rating_returns_the_stored_rating(db_path):
    accounts.authenticate(db_path, "efrat", "hunter2")
    assert accounts.get_rating(db_path, "efrat") == accounts.STARTING_RATING


def test_expected_score_is_half_for_equal_ratings():
    assert accounts.expected_score(1200, 1200) == pytest.approx(0.5)


def test_expected_score_favors_the_higher_rated_player():
    assert accounts.expected_score(1600, 1200) > 0.5
    assert accounts.expected_score(1200, 1600) < 0.5


def test_beating_a_much_higher_rated_opponent_gains_more_rating_than_beating_a_similar_one(db_path):
    """The user's own example: 1200 beating 1600 should gain more than
    1200 beating 1250."""
    accounts.authenticate(db_path, "underdog_a", "pw")
    accounts.authenticate(db_path, "underdog_b", "pw")
    accounts.authenticate(db_path, "favorite", "pw")
    accounts.authenticate(db_path, "near_peer", "pw")

    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE users SET rating = 1600 WHERE username = 'favorite'")
        connection.execute("UPDATE users SET rating = 1250 WHERE username = 'near_peer'")

    new_a, _ = accounts.update_ratings_after_game(db_path, winner_username="underdog_a", loser_username="favorite")
    new_b, _ = accounts.update_ratings_after_game(db_path, winner_username="underdog_b", loser_username="near_peer")

    gain_vs_favorite = new_a - accounts.STARTING_RATING
    gain_vs_near_peer = new_b - accounts.STARTING_RATING
    assert gain_vs_favorite > gain_vs_near_peer > 0


def test_update_ratings_after_game_moves_the_loser_down_and_winner_up_for_equal_ratings(db_path):
    accounts.authenticate(db_path, "alice", "pw")
    accounts.authenticate(db_path, "bob", "pw")

    new_winner, new_loser = accounts.update_ratings_after_game(db_path, winner_username="alice", loser_username="bob")

    assert new_winner == accounts.STARTING_RATING + accounts.ELO_K_FACTOR // 2
    assert new_loser == accounts.STARTING_RATING - accounts.ELO_K_FACTOR // 2
    assert accounts.get_rating(db_path, "alice") == new_winner
    assert accounts.get_rating(db_path, "bob") == new_loser

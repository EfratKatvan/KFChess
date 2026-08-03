import asyncio

from kungfu_chess.server import accounts
from kungfu_chess.server.accounts_client import AccountsClient


def test_register_over_http_creates_the_account_at_the_starting_rating(accounts_base_url):
    asyncio.run(_register_scenario(accounts_base_url))


async def _register_scenario(accounts_base_url):
    client = AccountsClient(accounts_base_url)

    result = await client.register("efrat", "hunter2")

    assert result.success is True
    assert result.rating == accounts.STARTING_RATING
    await client.close()


def test_register_over_http_rejects_a_taken_username(accounts_base_url):
    asyncio.run(_duplicate_register_scenario(accounts_base_url))


async def _duplicate_register_scenario(accounts_base_url):
    client = AccountsClient(accounts_base_url)
    await client.register("efrat", "hunter2")

    result = await client.register("efrat", "some-other-password")

    assert result.success is False
    assert result.reason is not None
    await client.close()


def test_login_over_http_with_the_right_password_succeeds(accounts_base_url):
    asyncio.run(_login_scenario(accounts_base_url))


async def _login_scenario(accounts_base_url):
    client = AccountsClient(accounts_base_url)
    await client.register("efrat", "hunter2")

    result = await client.login("efrat", "hunter2")

    assert result.success is True
    assert result.rating == accounts.STARTING_RATING
    await client.close()


def test_login_over_http_with_the_wrong_password_fails(accounts_base_url):
    asyncio.run(_wrong_password_scenario(accounts_base_url))


async def _wrong_password_scenario(accounts_base_url):
    client = AccountsClient(accounts_base_url)
    await client.register("efrat", "hunter2")

    result = await client.login("efrat", "wrong-password")

    assert result.success is False
    assert result.reason is not None
    await client.close()


def test_get_rating_over_http_returns_none_for_an_unknown_username(accounts_base_url):
    asyncio.run(_unknown_rating_scenario(accounts_base_url))


async def _unknown_rating_scenario(accounts_base_url):
    client = AccountsClient(accounts_base_url)

    assert await client.get_rating("nobody") is None
    await client.close()


def test_get_rating_over_http_returns_the_stored_rating(accounts_base_url):
    asyncio.run(_stored_rating_scenario(accounts_base_url))


async def _stored_rating_scenario(accounts_base_url):
    client = AccountsClient(accounts_base_url)
    await client.register("efrat", "hunter2")

    assert await client.get_rating("efrat") == accounts.STARTING_RATING
    await client.close()


def test_update_ratings_after_game_over_http_moves_winner_up_and_loser_down(accounts_base_url):
    asyncio.run(_update_ratings_scenario(accounts_base_url))


async def _update_ratings_scenario(accounts_base_url):
    client = AccountsClient(accounts_base_url)
    await client.register("alice", "pw")
    await client.register("bob", "pw")

    new_winner, new_loser = await client.update_ratings_after_game("alice", "bob")

    assert new_winner == accounts.STARTING_RATING + accounts.ELO_K_FACTOR // 2
    assert new_loser == accounts.STARTING_RATING - accounts.ELO_K_FACTOR // 2
    assert await client.get_rating("alice") == new_winner
    assert await client.get_rating("bob") == new_loser
    await client.close()


def test_accounts_service_writes_land_in_the_same_db_path_fixture(db_path, accounts_base_url):
    """Confirms the HTTP round-trip actually reaches db_path's own
    sqlite file, not some other database - the accounts_base_url
    fixture is bound to this same db_path (see conftest.py)."""
    asyncio.run(_shared_db_scenario(db_path, accounts_base_url))


async def _shared_db_scenario(db_path, accounts_base_url):
    client = AccountsClient(accounts_base_url)

    await client.register("efrat", "hunter2")

    assert accounts.get_rating(db_path, "efrat") == accounts.STARTING_RATING
    await client.close()

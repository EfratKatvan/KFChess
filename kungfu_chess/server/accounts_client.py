from __future__ import annotations

from typing import Optional, Tuple

import aiohttp

from kungfu_chess.server.accounts import AuthResult

ACCOUNTS_SERVICE_URL = "http://localhost:8766"

"""HTTP adapter the rest of the server talks to the Accounts/Ratings API
Service through - matchmaker.py, game_room.py and ws_gateway.py call only
this, never accounts.py or a db_path directly (Server_Design.md
section 6: the accounts DB is reachable only through one service, not
from every ephemeral worker). accounts_service.py is the other half of
this ports-and-adapters split (section 13.2): it wraps the exact same
accounts.py logic in REST handlers this client calls."""


class AccountsClient:
    def __init__(self, base_url: str = ACCOUNTS_SERVICE_URL) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        await self._session.close()

    async def login(self, username: str, password: str) -> AuthResult:
        return await self._auth_request("login", username, password)

    async def register(self, username: str, password: str) -> AuthResult:
        return await self._auth_request("register", username, password)

    async def _auth_request(self, endpoint: str, username: str, password: str) -> AuthResult:
        async with self._session.post(
            f"{self._base_url}/{endpoint}", json={"username": username, "password": password}
        ) as response:
            data = await response.json()
        return AuthResult(
            success=data["success"], rating=data.get("rating"), reason=data.get("reason"), token=data.get("token")
        )

    async def get_rating(self, username: str) -> Optional[int]:
        async with self._session.get(f"{self._base_url}/ratings/{username}") as response:
            if response.status == 404:
                return None
            data = await response.json()
        return data["rating"]

    async def update_ratings_after_game(self, winner_username: str, loser_username: str) -> Tuple[int, int]:
        async with self._session.post(
            f"{self._base_url}/ratings/update",
            json={"winner_username": winner_username, "loser_username": loser_username},
        ) as response:
            data = await response.json()
        return data["winner_rating"], data["loser_rating"]


def get_client(base_url: str = ACCOUNTS_SERVICE_URL) -> AccountsClient:
    """A new AccountsClient - mirrors redis_client.get_client()'s own
    choice, and for the same reason: an aiohttp.ClientSession is bound
    to the event loop that created it, and this server's tests each run
    their own asyncio.run() (its own fresh event loop), so a cached
    process-wide singleton would break on the next test. Production
    only ever constructs one (ws_gateway.py's run()), so there's no real
    cost either way."""
    return AccountsClient(base_url)

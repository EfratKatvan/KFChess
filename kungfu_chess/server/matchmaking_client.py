from __future__ import annotations

import os
from dataclasses import asdict
from typing import Optional

import aiohttp

from kungfu_chess.server.auth_token import TokenClaims

# Env-overridable (Stage 5, section 17): ws_gateway.py runs in its own
# container, reaching the Matchmaking Service container by its compose
# service name, not "localhost".
MATCHMAKING_SERVICE_URL = os.environ.get("MATCHMAKING_SERVICE_URL", "http://localhost:8768")

"""HTTP adapter ws_gateway.py talks to the Matchmaking Service through -
mirrors accounts_client.py's own ports-and-adapters split exactly
(matchmaking_service.py is this client's other half, the same way
accounts_service.py is accounts_client.py's). Only carries the
request/response half of the protocol (connect/message/leave_relay/
disconnect) - the async-push half (a match found by someone else's
request, or a seek timeout) arrives over Redis Pub/Sub instead, read
directly by ws_gateway.py using the same redis_client it already holds
for the Stage 1b revocation check, not through this class."""


class MatchmakingClient:
    def __init__(self, base_url: str = MATCHMAKING_SERVICE_URL) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        await self._session.close()

    async def connect(self, connection_id: str, username: str, claims: Optional[TokenClaims]) -> bool:
        async with self._session.post(
            f"{self._base_url}/connect",
            json={"connection_id": connection_id, "username": username, "claims": asdict(claims) if claims else None},
        ) as response:
            data = await response.json()
        return data["accepted"]

    async def send_message(self, connection_id: str, raw: str) -> None:
        async with self._session.post(
            f"{self._base_url}/message", json={"connection_id": connection_id, "raw": raw}
        ):
            pass

    async def leave_relay(self, connection_id: str) -> None:
        async with self._session.post(f"{self._base_url}/leave_relay", json={"connection_id": connection_id}):
            pass

    async def disconnect(self, connection_id: str) -> None:
        async with self._session.post(f"{self._base_url}/disconnect", json={"connection_id": connection_id}):
            pass


def get_client(base_url: str = MATCHMAKING_SERVICE_URL) -> MatchmakingClient:
    """A new MatchmakingClient - mirrors accounts_client.py's own
    get_client() and for the same reason (an aiohttp.ClientSession is
    bound to the event loop that created it)."""
    return MatchmakingClient(base_url)

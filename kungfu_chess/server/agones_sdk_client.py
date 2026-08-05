from __future__ import annotations

import logging
from typing import Any, Dict

import aiohttp

logger = logging.getLogger(__name__)

# Server_Design.md section 3 (Stage 7): the Agones SDK sidecar every
# GameServer pod gets automatically injected with - its REST gateway
# (confirmed against Agones' own sdk-server source: gRPC on 9357, this
# HTTP+JSON gateway on 9358), always reachable at localhost since the
# sidecar shares this pod's network namespace. Deliberately not the
# official `agones` PyPI package (pulls in grpcio/protobuf for four
# calls this project's existing aiohttp dependency already covers) -
# same reasoning accounts_client.py/matchmaking_client.py already
# apply to every other HTTP-shaped dependency here.
SDK_BASE_URL = "http://localhost:9358"


class AgonesSdkClient:
    """Talks to *this pod's own* Agones SDK sidecar - never another
    pod's. Used by game_shard.py to participate in the GameServer
    Ready/Health state machine a Fleet relies on to know which replicas
    are actually eligible for a new GameServerAllocation (see
    agones_allocation_client.py, the other, K8s-API-facing half of this
    integration - that one calls the sidecar of whichever GameServer
    Agones itself picks, this one only ever calls its own)."""

    def __init__(self, base_url: str = SDK_BASE_URL) -> None:
        self._base_url = base_url

    async def ready(self) -> None:
        """Flips this GameServer from Scheduled/not-ready into Ready -
        i.e. eligible for a Fleet's "N Ready replicas" count and for
        GameServerAllocation to select it. Call once, after serve() has
        actually bound the listening socket (game_shard.py's run) -
        never before this process can genuinely accept a HostSeatMessage."""
        await self._post("/ready")

    async def health(self) -> None:
        """One heartbeat tick of Agones' own SDK-driven health check
        (spec.health.periodSeconds/failureThreshold on the Fleet - see
        k8s/game-shard-fleet.yaml) - independent of, and in addition to,
        the existing Kubernetes livenessProbe/readinessProbe on port
        9100's /metrics: that one catches "process wedged/OOM," this
        one specifically says "this room-hosting process is alive and
        can still reach its own sidecar," a different failure mode."""
        await self._post("/health")

    async def shutdown(self) -> None:
        """Lets Agones cycle this GameServer out cleanly (planned
        rolling upgrades) rather than waiting for a liveness-probe
        failure - not called from any per-room lifecycle path, since
        this app's replicas host many rooms over time, not one each."""
        await self._post("/shutdown")

    async def get_gameserver(self) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self._base_url}/gameserver") as response:
                response.raise_for_status()
                return await response.json()

    async def _post(self, path: str) -> None:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self._base_url}{path}", json={}) as response:
                response.raise_for_status()

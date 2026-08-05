from __future__ import annotations

import logging
import ssl
from pathlib import Path
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# Server_Design.md section 3 (Stage 7): a plain HTTP POST against the
# in-cluster Kubernetes aggregated API - confirmed as a first-class,
# documented path (site/content/en/docs/Guides/access-api.md), not a
# workaround. Deliberately not the `kubernetes` Python client (an
# unjustified new dependency for one endpoint) and not Agones' separate
# Allocator Service (mTLS, built specifically for callers *outside* the
# cluster - this caller already runs in-cluster with its own
# ServiceAccount, exactly the auth mechanism the Allocator Service
# exists to let external callers skip).
_SERVICEACCOUNT_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
_K8S_API_HOST = "https://kubernetes.default.svc"


class AgonesAllocationClient:
    """Allocates one Ready GameServer from a named Fleet - called once
    per brand-new room (matchmaker.py's _pair/_join_room, at the exact
    point both HostSeatMessages are about to be constructed), never
    per-seat: this is the single choke point that decides "which
    replica," so both seats' independent Gateway connections resolve
    the *same* address afterward via room_shard_registry, with no race
    and no second allocation call to coordinate with."""

    def __init__(self, namespace: str, serviceaccount_dir: Path = _SERVICEACCOUNT_DIR) -> None:
        self._namespace = namespace
        self._token_path = serviceaccount_dir / "token"
        self._ca_path = serviceaccount_dir / "ca.crt"

    def _bearer_token(self) -> str:
        return self._token_path.read_text().strip()

    def _ssl_context(self) -> ssl.SSLContext:
        # aiohttp's own ssl= parameter requires an SSLContext/bool/
        # Fingerprint, never a bare path string (confirmed the hard way
        # against a real cluster: passing str(self._ca_path) directly
        # raises "ssl should be SSLContext, bool, Fingerprint or None"
        # before the request is ever sent).
        return ssl.create_default_context(cafile=str(self._ca_path))

    async def allocate(self, fleet_name: str) -> Optional[str]:
        """Returns the allocated GameServer's dialable "host:port", or
        None if allocation failed (Fleet at capacity, RBAC missing,
        API unreachable) - the caller treats a None exactly like "no
        match could be placed," never a crash."""
        url = f"{_K8S_API_HOST}/apis/allocation.agones.dev/v1/namespaces/{self._namespace}/gameserverallocations"
        body = {
            "apiVersion": "allocation.agones.dev/v1",
            "kind": "GameServerAllocation",
            "spec": {"selectors": [{"matchLabels": {"agones.dev/fleet": fleet_name}}]},
        }
        headers = {"Authorization": f"Bearer {self._bearer_token()}"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=body, headers=headers, ssl=self._ssl_context()
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
        except Exception as error:  # noqa: BLE001 - allocation failure is a normal, handled outcome, not a crash
            logger.warning("GameServerAllocation against fleet %s failed: %s", fleet_name, error)
            return None

        status = data.get("status", {})
        if status.get("state") != "Allocated":
            logger.warning("GameServerAllocation against fleet %s did not allocate: %r", fleet_name, status)
            return None

        # status.addresses (plural) is what portPolicy: None GameServers
        # actually need, and it's a *mixed* list (confirmed against a
        # real allocation response - not just docs) - typically
        # InternalIP/Hostname/PodIP entries together. status.address
        # (singular) and the list's InternalIP entry both resolve to
        # the *Node's* address under portPolicy: None, which no
        # in-cluster caller can dial to reach one specific replica
        # among several on the same node - only the PodIP entry is
        # actually this GameServer's own address. Ports carries the
        # one named port our Fleet exposes.
        addresses = status.get("addresses") or []
        ports = status.get("ports") or []
        pod_ip = next((entry["address"] for entry in addresses if entry.get("type") == "PodIP"), None)
        if pod_ip is None or not ports:
            logger.warning("GameServerAllocation response missing a PodIP address/ports: %r", status)
            return None
        port = ports[0]["port"]
        return f"{pod_ip}:{port}"

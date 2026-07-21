from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from websockets.asyncio.client import connect

from kungfu_chess.client.client_state import ClientState, apply_message
from kungfu_chess.server.messages import LoginMessage
from kungfu_chess.server.serialization import deserialize_message, serialize_message

"""The client's Transport layer: owns the actual WebSocket connection
and the background thread it runs on - knows nothing about game rules,
clicks, or drawing, only how to get bytes to/from the server and hand
decoded messages to client_state.apply_message."""

logger = logging.getLogger(__name__)


@dataclass
class ClientBox:
    """The mutable, cross-thread handoff point: the network thread
    writes ws/loop once (on connect) and state on every message; the
    main render thread only ever reads. Safe without locks because each
    attribute write/read is a single reference assignment, atomic under
    the GIL - the same idiom image_view.py uses for current["session"]."""

    state: ClientState = field(default_factory=ClientState)
    ws: Optional[Any] = None
    loop: Optional[asyncio.AbstractEventLoop] = None


def send(box: ClientBox, message: Any) -> None:
    if box.loop is None or box.ws is None:
        return
    asyncio.run_coroutine_threadsafe(box.ws.send(serialize_message(message)), box.loop)


def network_thread_main(server_uri: str, username: str, password: str, box: ClientBox) -> None:
    async def client_main() -> None:
        async with connect(server_uri) as ws:
            box.ws = ws
            box.loop = asyncio.get_running_loop()
            logger.info("connected to %s as %s", server_uri, username)
            await ws.send(serialize_message(LoginMessage(username=username, password=password)))
            async for raw in ws:
                box.state = apply_message(deserialize_message(raw), box.state)

    try:
        asyncio.run(client_main())
    except Exception as error:
        logger.warning("disconnected from server: %s", error)
        box.state = ClientState(phase="disconnected")

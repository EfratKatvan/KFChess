from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from websockets.asyncio.client import connect

from kungfu_chess.assets_config import DEFAULT_PIECE_SET
from kungfu_chess.client import sound, token_store
from kungfu_chess.client.client_state import ClientState, apply_message, events_since
from kungfu_chess.client.phases import Phase
from kungfu_chess.server.messages import LoggedOutMessage, LoginFailedMessage, LoginOkMessage, TokenLoginMessage
from kungfu_chess.server.serialization import deserialize_message, serialize_message

"""The client's Transport layer: owns the actual WebSocket connection
and the background thread it runs on - knows nothing about game rules,
clicks, or drawing, only how to get bytes to/from the server and hand
decoded messages to client_state.apply_message. Also reacts to each
message with a short sound (client/sound.py), the one non-drawing side
effect that lives here rather than in view/network_presentation.py -
it needs to fire once per message, not once per render frame, and
events_since's diff only makes sense against the state right before
this exact message.

Sound playback is handed to the event loop's executor (run_in_executor,
fire-and-forget - not awaited) rather than called directly here.
winsound.PlaySound's SND_ASYNC flag is documented as returning
immediately, but this loop must never bet the connection on that -
if it ever did block (a flaky audio driver, device contention with
another instance of this same app on the same machine, ...), calling
it inline here would freeze this exact async for loop forever: no
more incoming messages get processed, box.state stops updating, and
the render loop just keeps redrawing whatever it last had - which
looks exactly like a frozen/gray window from the outside, with no
exception anywhere to explain it. Running it on the executor means
even a hung PlaySound call only strands one thread-pool thread, never
this one."""

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
    piece_set: str = DEFAULT_PIECE_SET  # chosen once on the skin_menu screen; read every frame by the render loop


def send(box: ClientBox, message: Any) -> None:
    if box.loop is None or box.ws is None:
        return
    asyncio.run_coroutine_threadsafe(box.ws.send(serialize_message(message)), box.loop)


def _play_sound_safely(events: Any) -> None:
    """A missed beep is never worth losing the connection over - unlike
    every other except-block in this project, this one really is just
    best-effort noise-making, so a blanket Exception guard belongs here
    even though it wouldn't elsewhere."""
    try:
        sound.play_events(events)
    except Exception as error:
        logger.debug("sound playback failed (%s) - continuing without it", error)


def _handle_session_persistence(message: Any, initial_message: Any) -> None:
    """The other side effect that lives here (Stage 1b), alongside sound
    playback - saving/clearing the locally-stored session (client/
    token_store.py) so a later run can offer "Continue as X" instead of
    retyping a password. A rejected TokenLoginMessage also clears
    whatever was saved (it's no good anymore); an *ordinary* wrong-
    password LoginMessage/RegisterMessage failure must not touch an
    unrelated saved session, which is exactly what checking
    initial_message's own type (not just the response) distinguishes."""
    if isinstance(message, LoginOkMessage):
        token_store.save_token(message.username, message.token)
    elif isinstance(message, LoggedOutMessage):
        token_store.clear_token()
    elif isinstance(message, LoginFailedMessage) and isinstance(initial_message, TokenLoginMessage):
        token_store.clear_token()


def network_thread_main(server_uri: str, initial_message: Any, box: ClientBox) -> None:
    """initial_message is a LoginMessage, RegisterMessage, or (Stage 1b)
    TokenLoginMessage, already built by network_client_view.py from
    whatever was typed into (or, for a saved session, already sitting
    on) the in-canvas login screen (see its login_entry phase) - this
    layer just sends whichever one it's handed, without needing to know
    the difference itself beyond _handle_session_persistence above.
    Only started once that's actually submitted - no connection exists
    before then."""
    async def client_main() -> None:
        async with connect(server_uri) as ws:
            box.ws = ws
            box.loop = asyncio.get_running_loop()
            logger.info("connected to %s as %s", server_uri, initial_message.username)
            await ws.send(serialize_message(initial_message))
            async for raw in ws:
                message = deserialize_message(raw)
                new_state = apply_message(message, box.state)
                events = events_since(box.state, new_state)
                # box.state is read next by the main thread's render loop
                # (network_client_view.py) - no lock needed, see ClientBox.
                # Updated before the sound dispatch below, so a slow/stuck
                # executor thread can never delay this.
                box.state = new_state
                _handle_session_persistence(message, initial_message)
                if events:
                    box.loop.run_in_executor(None, _play_sound_safely, events)

    try:
        asyncio.run(client_main())
    except Exception as error:
        logger.warning("disconnected from server: %s", error)
        box.state = ClientState(phase=Phase.DISCONNECTED)

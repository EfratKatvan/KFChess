from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, DefaultDict, List, Type

"""A minimal type-keyed publish/subscribe bus - decouples event
producers (GameEngine, RealTimeArbiter) from consumers (MoveLogObserver,
ScoreObserver, or anything else that wants to react to a game event)
without the producer needing to know who, if anyone, is listening.
GameEngine/RealTimeArbiter each own one of these internally and publish
their existing MoveLoggedEvent/PieceCapturedEvent dataclasses
(model/game_state.py) onto it - GameObserver (that module's fixed
on_move_logged/on_piece_captured interface) stays the ergonomic,
typed surface callers register through via add_observer, which now
subscribes those bound methods to the right event type here instead of
appending to a plain list and hand-rolling the fan-out itself."""


class Bus:
    def __init__(self) -> None:
        self._subscribers: DefaultDict[Type[Any], List[Callable[[Any], None]]] = defaultdict(list)

    def subscribe(self, event_type: Type[Any], handler: Callable[[Any], None]) -> None:
        self._subscribers[event_type].append(handler)

    def publish(self, event: Any) -> None:
        for handler in self._subscribers[type(event)]:
            handler(event)

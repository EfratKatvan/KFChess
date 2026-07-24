from dataclasses import dataclass

from kungfu_chess.events.bus import Bus


@dataclass(frozen=True)
class _Ping:
    value: int


@dataclass(frozen=True)
class _Pong:
    value: int


def test_publish_calls_a_subscriber_registered_for_that_exact_event_type():
    received = []
    bus = Bus()
    bus.subscribe(_Ping, received.append)

    bus.publish(_Ping(1))

    assert received == [_Ping(1)]


def test_publish_calls_every_subscriber_in_registration_order():
    calls = []
    bus = Bus()
    bus.subscribe(_Ping, lambda event: calls.append(("first", event)))
    bus.subscribe(_Ping, lambda event: calls.append(("second", event)))

    bus.publish(_Ping(1))

    assert calls == [("first", _Ping(1)), ("second", _Ping(1))]


def test_publish_does_not_call_a_subscriber_registered_for_a_different_event_type():
    received = []
    bus = Bus()
    bus.subscribe(_Ping, received.append)

    bus.publish(_Pong(1))

    assert received == []


def test_publish_with_no_subscribers_does_not_raise():
    Bus().publish(_Ping(1))


def test_two_bus_instances_do_not_share_subscribers():
    received = []
    first_bus, second_bus = Bus(), Bus()
    first_bus.subscribe(_Ping, received.append)

    second_bus.publish(_Ping(1))

    assert received == []

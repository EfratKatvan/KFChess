from kungfu_chess.client import sound
from kungfu_chess.client.client_state import CAPTURE_EVENT, GAME_OVER_EVENT, GAME_START_EVENT, MOVE_EVENT


class _FakeWinsound:
    SND_FILENAME = 1
    SND_ASYNC = 2

    def __init__(self) -> None:
        self.calls = []

    def PlaySound(self, path, flags) -> None:
        self.calls.append((path, flags))


def test_play_events_plays_the_file_for_each_known_event(monkeypatch):
    fake = _FakeWinsound()
    monkeypatch.setattr(sound, "winsound", fake)

    sound.play_events(frozenset({MOVE_EVENT}))

    assert len(fake.calls) == 1
    path, flags = fake.calls[0]
    assert path.endswith("move.wav")
    assert flags == fake.SND_FILENAME | fake.SND_ASYNC


def test_play_events_plays_one_call_per_distinct_event(monkeypatch):
    fake = _FakeWinsound()
    monkeypatch.setattr(sound, "winsound", fake)

    sound.play_events(frozenset({MOVE_EVENT, CAPTURE_EVENT, GAME_START_EVENT, GAME_OVER_EVENT}))

    played_files = {path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for path, _ in fake.calls}
    assert played_files == {"move.wav", "capture.wav", "game_start.wav", "game_over.wav"}


def test_play_events_ignores_unknown_event_tags(monkeypatch):
    fake = _FakeWinsound()
    monkeypatch.setattr(sound, "winsound", fake)

    sound.play_events(frozenset({"not_a_real_event"}))

    assert fake.calls == []


def test_play_events_with_no_events_plays_nothing(monkeypatch):
    fake = _FakeWinsound()
    monkeypatch.setattr(sound, "winsound", fake)

    sound.play_events(frozenset())

    assert fake.calls == []


def test_play_events_is_a_no_op_when_winsound_is_unavailable(monkeypatch):
    monkeypatch.setattr(sound, "winsound", None)  # what this module sets itself to off Windows

    sound.play_events(frozenset({MOVE_EVENT}))  # must not raise


def test_play_events_swallows_a_playback_failure(monkeypatch):
    class _FailingWinsound(_FakeWinsound):
        def PlaySound(self, path, flags) -> None:
            raise RuntimeError("no audio device")

    monkeypatch.setattr(sound, "winsound", _FailingWinsound())

    sound.play_events(frozenset({MOVE_EVENT}))  # must not raise


def test_sound_asset_files_actually_exist_on_disk():
    """The whole point of switching from winsound.Beep to PlaySound was
    to play real, distinct short sounds - a missing file for a mapped
    event would silently no-op (see _path_for), so this catches that
    case that a mocked winsound test above never would."""
    for filename in sound._FILENAME_BY_EVENT.values():
        assert (sound._SOUNDS_DIR / filename).is_file()

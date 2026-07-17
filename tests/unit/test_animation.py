import pytest

from kungfu_chess.assets_config import PIECE_SETS, MissingAssetError
from kungfu_chess.view.animation import AnimationCache, StateAnimation, frame_index


def test_frame_index_clamps_to_last_frame_when_not_looping():
    animation = StateAnimation(frames=[object(), object(), object()], frames_per_sec=1, is_loop=False)
    assert frame_index(elapsed_ms=10_000, animation=animation) == 2


def test_frame_index_wraps_around_when_looping():
    animation = StateAnimation(frames=[object(), object(), object()], frames_per_sec=1, is_loop=True)
    assert frame_index(elapsed_ms=3500, animation=animation) == 0


def test_loading_an_unknown_piece_code_raises_missing_asset_error():
    with pytest.raises(MissingAssetError, match="NOPE"):
        AnimationCache().load("NOPE", "idle", cell_size=100)


def test_loading_an_unknown_state_raises_missing_asset_error():
    with pytest.raises(MissingAssetError, match="no_such_state"):
        AnimationCache().load("PW", "no_such_state", cell_size=100)


def test_loading_an_unknown_piece_set_raises_missing_asset_error():
    with pytest.raises(MissingAssetError, match="pieces99"):
        AnimationCache().load("PW", "idle", cell_size=100, piece_set="pieces99")


def test_both_shipped_piece_sets_load_successfully():
    cache = AnimationCache()
    for piece_set in PIECE_SETS:
        animation = cache.load("QW", "idle", cell_size=100, piece_set=piece_set)
        assert len(animation.frames) > 0


def test_cache_reuses_the_same_animation_object_for_the_same_key():
    cache = AnimationCache()
    first = cache.load("PW", "idle", cell_size=100, piece_set="pieces2")
    second = cache.load("PW", "idle", cell_size=100, piece_set="pieces2")
    assert first is second


def test_two_separate_caches_do_not_share_state():
    first_cache = AnimationCache()
    second_cache = AnimationCache()
    first_cache.load("PW", "idle", cell_size=100, piece_set="pieces2")
    assert second_cache._animations == {}

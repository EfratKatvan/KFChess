from config.constants import build_legal_tokens


def test_includes_empty_cell():
    assert "." in build_legal_tokens()


def test_includes_all_color_piece_combinations():
    tokens = build_legal_tokens()
    for color in ("w", "b"):
        for piece in ("K", "Q", "R", "B", "N", "P"):
            assert f"{color}{piece}" in tokens


def test_excludes_invalid_token():
    assert "xX" not in build_legal_tokens()


def test_token_count_is_exact():
    assert len(build_legal_tokens()) == 13
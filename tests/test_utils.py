from src.utils import _deep_merge


def test_deep_merge():
    base = {"a": 1, "b": {"c": 2, "d": 3}}
    override = {"b": {"c": 4, "e": 5}, "f": 6}
    merged = _deep_merge(base, override)
    assert merged == {"a": 1, "b": {"c": 4, "d": 3, "e": 5}, "f": 6}
    assert base == {"a": 1, "b": {"c": 2, "d": 3}}

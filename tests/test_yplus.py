from __future__ import annotations

from ofti.tools.yplus import _first_float, _float_after, _parse_yplus_stats


def test_parse_yplus_stats() -> None:
    text = """yPlus: min 0.12 max 45.6 avg 3.4
Some other line
"""
    stats = _parse_yplus_stats(text)
    assert stats["min"] == "0.12"
    assert stats["max"] == "45.6"
    assert stats["avg"] == "3.4"


def test_yplus_float_helpers_no_match() -> None:
    assert _first_float("value 1.23") == "1.23"
    assert _float_after("min", "min: 0.1") == "0.1"
    assert _first_float("no values here") is None
    assert _float_after("min", "no min token") is None

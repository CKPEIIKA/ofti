from __future__ import annotations

from ofti.tools import _parse_yplus_stats


def test_parse_yplus_stats() -> None:
    text = """yPlus: min 0.12 max 45.6 avg 3.4
Some other line
"""
    stats = _parse_yplus_stats(text)
    assert stats["min"] == "0.12"
    assert stats["max"] == "45.6"
    assert stats["avg"] == "3.4"

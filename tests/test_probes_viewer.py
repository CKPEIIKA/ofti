from __future__ import annotations

from ofti.tools.logs_probes import _parse_probe_line, _parse_probe_series


def test_parse_probe_series_scalar() -> None:
    text = """# Probe data
0 1.0 2.0 3.0
0.5 4.0 5.0 6.0
"""
    times, values, count = _parse_probe_series(text)
    assert times == [0.0, 0.5]
    assert values == [1.0, 4.0]
    assert count == 3


def test_parse_probe_series_vector() -> None:
    text = """# t U0 U1
0 (1 0 0) (0 2 0)
1 (3 4 0) (0 0 5)
"""
    times, values, count = _parse_probe_series(text)
    assert times == [0.0, 1.0]
    assert values[0] == 1.0
    assert round(values[1], 6) == 5.0
    assert count == 2


def test_parse_probe_line_vector_sample() -> None:
    parsed = _parse_probe_line("0.1 (1 2 3)")
    assert parsed is not None
    time, values, count = parsed
    assert time == 0.1
    assert round(values[0], 6) == 3.741657
    assert count == 1

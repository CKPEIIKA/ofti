from __future__ import annotations

from ofti.core.plot import block_bar, braille_line_plot, sparkline


def test_sparkline_resamples_and_handles_empty_values() -> None:
    assert sparkline([]) == ""
    assert sparkline([None, 1, 1, 1]) == "▁▁▁"
    line = sparkline([0, 1, 2, 3, 4], width=3)
    assert len(line) == 3
    assert line[0] == "▁"
    assert line[-1] == "█"


def test_block_bar_scales_to_width() -> None:
    assert block_bar(5, maximum=10, width=10) == "█████░░░░░"
    assert block_bar(None, width=10) == ""


def test_braille_line_plot_returns_braille_cells() -> None:
    lines = braille_line_plot([0, 1, 0, 2, 1], width=8, height=3)
    assert len(lines) == 3
    assert any("\u2800" < char <= "\u28ff" for line in lines for char in line)

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

_SPARKS = "▁▂▃▄▅▆▇█"
_BRAILLE_BASE = 0x2800
_BRAILLE_DOTS = {
    (0, 0): 0x01,
    (0, 1): 0x02,
    (0, 2): 0x04,
    (0, 3): 0x40,
    (1, 0): 0x08,
    (1, 1): 0x10,
    (1, 2): 0x20,
    (1, 3): 0x80,
}


def sparkline(values: Iterable[float | int | None], *, width: int | None = None) -> str:
    samples = _clean_values(values)
    if not samples:
        return ""
    if width is not None and width > 0:
        samples = _resample(samples, width)
    low = min(samples)
    high = max(samples)
    if high == low:
        return _SPARKS[0] * len(samples)
    scale = (len(_SPARKS) - 1) / (high - low)
    return "".join(_SPARKS[round((value - low) * scale)] for value in samples)


def block_bar(
    value: float | int | None,
    *,
    maximum: float | int | None = None,
    width: int = 20,
) -> str:
    if value is None or width <= 0:
        return ""
    top = float(maximum if maximum is not None else value)
    if top <= 0 or not math.isfinite(top):
        return "" if value <= 0 else "█" * width
    filled = max(0, min(width, round((float(value) / top) * width)))
    return "█" * filled + "░" * (width - filled)


def braille_line_plot(
    values: Sequence[float | int | None],
    *,
    width: int = 40,
    height: int = 8,
) -> list[str]:
    samples = _clean_values(values)
    if not samples or width <= 0 or height <= 0:
        return []
    samples = _resample(samples, max(2, width * 2))
    low = min(samples)
    high = max(samples)
    y_span = height * 4 - 1
    x_span = width * 2 - 1
    cells = [[0 for _ in range(width)] for _ in range(height)]
    for index, value in enumerate(samples):
        x_dot = round(index * x_span / max(1, len(samples) - 1))
        if high == low:
            y_dot_from_bottom = y_span // 2
        else:
            y_dot_from_bottom = round((value - low) * y_span / (high - low))
        y_dot = y_span - y_dot_from_bottom
        cell_x, dot_col = divmod(x_dot, 2)
        cell_y, dot_row = divmod(y_dot, 4)
        cells[cell_y][cell_x] |= _BRAILLE_DOTS[(dot_col, dot_row)]
    return ["".join(chr(_BRAILLE_BASE + cell) for cell in row).rstrip() for row in cells]


def _clean_values(values: Iterable[float | int | None]) -> list[float]:
    cleaned: list[float] = []
    for value in values:
        if value is None:
            continue
        number = float(value)
        if math.isfinite(number):
            cleaned.append(number)
    return cleaned


def _resample(values: Sequence[float], width: int) -> list[float]:
    if width <= 0 or len(values) <= width:
        return list(values)
    if width == 1:
        return [values[-1]]
    step = (len(values) - 1) / (width - 1)
    return [values[round(index * step)] for index in range(width)]

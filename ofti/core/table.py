from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

Column = tuple[str, str]


def render_table(
    rows: Sequence[Mapping[str, Any]],
    columns: Sequence[Column],
    *,
    empty: str = "(none)",
) -> list[str]:
    if not rows:
        return [empty]

    headers = [label for _key, label in columns]
    widths = list(map(len, headers))
    text_rows: list[list[str]] = []
    for row in rows:
        rendered = [_cell(row.get(key)) for key, _label in columns]
        widths = [
            max(width, len(value))
            for width, value in zip(widths, rendered, strict=True)
        ]
        text_rows.append(rendered)

    lines = [_row(headers, widths), _separator(widths)]
    lines.extend(_row(row, widths) for row in text_rows)
    return lines


def render_kv(rows: Sequence[tuple[str, Any]], *, empty: str = "(none)") -> list[str]:
    shaped = [{"key": key, "value": value} for key, value in rows]
    return render_table(shaped, [("key", "Key"), ("value", "Value")], empty=empty)


def _row(values: Sequence[str], widths: Sequence[int]) -> str:
    return "  ".join(
        value.ljust(width)
        for value, width in zip(values, widths, strict=True)
    ).rstrip()


def _separator(widths: Sequence[int]) -> str:
    return "  ".join("-" * width for width in widths).rstrip()


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)

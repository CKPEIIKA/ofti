from __future__ import annotations

from typing import Any


def fold_log_lines(lines: list[str], *, limit: int = 40) -> list[dict[str, Any]]:
    """Return signal-heavy log rows and fold generic solver chatter."""
    rows: list[dict[str, Any]] = []
    folded = 0
    for index, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        kind = _classify(line)
        if kind is None:
            folded += 1
            continue
        rows.append({"kind": kind, "message": line})
        if len(rows) >= limit:
            folded += sum(1 for item in lines[index + 1 :] if item.strip())
            break
    if folded:
        rows.append({"kind": "folded", "message": f"{folded} other lines"})
    return rows


def _classify(line: str) -> str | None:
    lowered = line.lower()
    checks = [
        (line.startswith("Time ="), "time"),
        ("courant number" in lowered or "comax" in lowered, "courant"),
        ("solving for" in lowered and "residual" in lowered, "residual"),
        ("fatal" in lowered or "error" in lowered, "error"),
        ("warning" in lowered, "warning"),
        ("executiontime" in lowered or "execution time" in lowered, "runtime"),
    ]
    for matched, kind in checks:
        if matched:
            return kind
    return None

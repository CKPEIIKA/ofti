from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from pathlib import Path

_RESIDUAL_RE = re.compile(
    r"Solving for\s+(?P<field>[^,\s]+).*?Initial residual = (?P<res>[0-9eE.+-]+)",
)


def parse_residuals(text: str) -> dict[str, list[float]]:
    residuals: dict[str, list[float]] = {}
    for line in text.splitlines():
        match = _RESIDUAL_RE.search(line)
        if not match:
            continue
        field = match.group("field")
        try:
            value = float(match.group("res"))
        except ValueError:
            continue
        residuals.setdefault(field, []).append(value)
    return residuals


async def tail_log_lines(path: Path, *, poll_interval: float = 0.25) -> AsyncIterator[str]:
    if not path.exists():
        return
    with path.open("r", errors="ignore") as handle:
        handle.seek(0, 2)
        while True:
            line = handle.readline()
            if line:
                yield line.rstrip("\n")
                continue
            await asyncio.sleep(poll_interval)

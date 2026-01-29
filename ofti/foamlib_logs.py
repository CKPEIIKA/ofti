from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

_RESIDUAL_RE = re.compile(
    r"Solving for\s+(?P<field>[^,\s]+).*?Initial residual = (?P<res>[0-9eE.+-]+)",
)
_TIME_RE = re.compile(r"^\s*Time\s*=\s*(?P<time>[0-9eE.+-]+)\s*$", re.MULTILINE)
_COURANT_RE = re.compile(
    r"Courant(?:\s+Number)?(?:\s+mean)?\s*[:=]\s*(?P<mean>[0-9eE.+-]+)"
    r".*?(?:max|maximum)\s*[:=]\s*(?P<max>[0-9eE.+-]+)",
    re.IGNORECASE,
)
_EXEC_TIME_RE = re.compile(
    r"ExecutionTime\s*=\s*(?P<exec>[0-9eE.+-]+)\s*s",
    re.IGNORECASE,
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


def parse_time_steps(text: str) -> list[float]:
    times: list[float] = []
    for match in _TIME_RE.finditer(text):
        try:
            times.append(float(match.group("time")))
        except ValueError:
            continue
    return times


def parse_courant_numbers(text: str) -> list[float]:
    values: list[float] = []
    for match in _COURANT_RE.finditer(text):
        try:
            values.append(float(match.group("max")))
        except ValueError:
            continue
    return values


def parse_execution_times(text: str) -> list[float]:
    values: list[float] = []
    for match in _EXEC_TIME_RE.finditer(text):
        try:
            values.append(float(match.group("exec")))
        except ValueError:
            continue
    return values


@dataclass(frozen=True)
class LogMetrics:
    times: list[float]
    courants: list[float]
    execution_times: list[float]


def parse_log_metrics(text: str) -> LogMetrics:
    return LogMetrics(
        times=parse_time_steps(text),
        courants=parse_courant_numbers(text),
        execution_times=parse_execution_times(text),
    )


def execution_time_deltas(execution_times: list[float]) -> list[float]:
    if len(execution_times) < 2:
        return []
    deltas: list[float] = []
    prev = execution_times[0]
    for current in execution_times[1:]:
        delta = current - prev
        if delta >= 0:
            deltas.append(delta)
        prev = current
    return deltas


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

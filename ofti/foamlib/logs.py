from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from ofti.foam.subprocess_utils import run_trusted

_RESIDUAL_RE = re.compile(
    r"Solving for\s+(?P<field>[^,\s]+).*?Initial residual = (?P<res>[0-9eE.+-]+)",
)
_TIME_RE = re.compile(r"^\s*Time\s*=\s*(?P<time>[0-9eE.+-]+)\s*$", re.MULTILINE)
_TIME_LINE_RE = re.compile(r"^\s*Time\s*=\s*(?P<time>[0-9eE.+-]+)\s*$")
_COURANT_RE = re.compile(
    r"Courant(?:\s+Number)?(?:\s+mean)?\s*[:=]\s*(?P<mean>[0-9eE.+-]+)"
    r".*?(?:max|maximum)\s*[:=]\s*(?P<max>[0-9eE.+-]+)",
    re.IGNORECASE,
)
_EXEC_TIME_RE = re.compile(
    r"ExecutionTime\s*=\s*(?P<exec>[0-9eE.+-]+)\s*s",
    re.IGNORECASE,
)
_DEFAULT_MAX_LOG_BYTES = 32 * 1024 * 1024
_DEFAULT_TAIL_MAX_BYTES = 8 * 1024 * 1024
_BASE_FILTER_TERMS = (
    "Time =",
    "ExecutionTime",
    "Courant",
    "deltaT",
    "iteration",
    "iter =",
    "Solving for",
)
_MAX_FILTER_TERMS = 96


def parse_residuals(text: str) -> dict[str, list[float]]:
    residuals: dict[str, list[float]] = {}
    for line in text.splitlines():
        if "Solving for" not in line or "Initial residual" not in line:
            continue
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
    for line in text.splitlines():
        if "Courant" not in line:
            continue
        match = _COURANT_RE.search(line)
        if match is None:
            continue
        try:
            values.append(float(match.group("max")))
        except ValueError:
            continue
    return values


def parse_execution_times(text: str) -> list[float]:
    values: list[float] = []
    for line in text.splitlines():
        if "ExecutionTime" not in line:
            continue
        match = _EXEC_TIME_RE.search(line)
        if match is None:
            continue
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
    times: list[float] = []
    courants: list[float] = []
    execution_times: list[float] = []
    for line in text.splitlines():
        _append_time_value(line, times)
        _append_courant_value(line, courants)
        _append_execution_time_value(line, execution_times)
    return LogMetrics(
        times=times,
        courants=courants,
        execution_times=execution_times,
    )


def parse_log_metrics_and_residuals(text: str) -> tuple[LogMetrics, dict[str, list[float]]]:
    times: list[float] = []
    courants: list[float] = []
    execution_times: list[float] = []
    residuals: dict[str, list[float]] = {}

    for line in text.splitlines():
        _append_time_value(line, times)
        _append_courant_value(line, courants)
        _append_execution_time_value(line, execution_times)
        _append_residual_value(line, residuals)

    return LogMetrics(
        times=times,
        courants=courants,
        execution_times=execution_times,
    ), residuals


def _append_time_value(line: str, values: list[float]) -> None:
    if "Time" not in line:
        return
    match = _TIME_LINE_RE.match(line)
    if match is None:
        return
    with suppress(ValueError):
        values.append(float(match.group("time")))


def _append_courant_value(line: str, values: list[float]) -> None:
    if "Courant" not in line:
        return
    match = _COURANT_RE.search(line)
    if match is None:
        return
    with suppress(ValueError):
        values.append(float(match.group("max")))


def _append_execution_time_value(line: str, values: list[float]) -> None:
    if "ExecutionTime" not in line:
        return
    match = _EXEC_TIME_RE.search(line)
    if match is None:
        return
    with suppress(ValueError):
        values.append(float(match.group("exec")))


def _append_residual_value(line: str, residuals: dict[str, list[float]]) -> None:
    if "Solving for" not in line or "Initial residual" not in line:
        return
    match = _RESIDUAL_RE.search(line)
    if match is None:
        return
    field = match.group("field")
    with suppress(ValueError):
        residuals.setdefault(field, []).append(float(match.group("res")))


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


def read_log_text(path: Path, *, max_bytes: int | None = _DEFAULT_MAX_LOG_BYTES) -> str:
    data, truncated = _read_tail_bytes(path, max_bytes=max_bytes)
    if truncated:
        first_newline = data.find(b"\n")
        if first_newline >= 0:
            data = data[first_newline + 1 :]
    return data.decode("utf-8", errors="ignore")


def read_log_text_filtered(
    path: Path,
    *,
    terms: list[str] | None = None,
    max_bytes: int | None = None,
) -> str:
    selected_terms = _filter_terms(terms)
    if max_bytes is not None:
        text = read_log_text(path, max_bytes=max_bytes)
        return _filter_lines(text, selected_terms)
    external = _rg_filter_file(path, selected_terms)
    if external is not None:
        return external
    text = read_log_text(path, max_bytes=max_bytes)
    return _filter_lines(text, selected_terms)


def read_log_tail_lines(
    path: Path,
    *,
    max_lines: int,
    max_bytes: int = _DEFAULT_TAIL_MAX_BYTES,
    chunk_size: int = 64 * 1024,
) -> list[str]:
    if max_lines <= 0:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if max_bytes <= 0:
        return []
    with path.open("rb") as handle:
        handle.seek(0, 2)
        end = handle.tell()
        if end <= 0:
            return []
        start = max(0, end - max_bytes)
        pos = end
        chunks: list[bytes] = []
        newline_count = 0
        while pos > start and newline_count <= max_lines:
            step = min(chunk_size, pos - start)
            pos -= step
            handle.seek(pos)
            block = handle.read(step)
            chunks.append(block)
            newline_count += block.count(b"\n")
    data = b"".join(reversed(chunks))
    if start > 0:
        first_newline = data.find(b"\n")
        if first_newline >= 0:
            data = data[first_newline + 1 :]
    lines = data.decode("utf-8", errors="ignore").splitlines()
    return lines[-max_lines:]


def _read_tail_bytes(path: Path, *, max_bytes: int | None) -> tuple[bytes, bool]:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        if max_bytes is None or max_bytes <= 0 or size <= max_bytes:
            handle.seek(0)
            return handle.read(), False
        handle.seek(-max_bytes, 2)
        return handle.read(max_bytes), True


def _filter_terms(terms: list[str] | None) -> list[str]:
    selected: list[str] = [str(term).strip() for term in _BASE_FILTER_TERMS if str(term).strip()]
    if terms:
        selected.extend([term.strip() for term in terms if term.strip()])
    unique: list[str] = []
    seen: set[str] = set()
    for term in selected:
        lowered = term.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique.append(term)
        if len(unique) >= _MAX_FILTER_TERMS:
            break
    return unique


def _filter_lines(text: str, terms: list[str]) -> str:
    if not terms:
        return text
    needles = [term.lower() for term in terms]
    lines = [
        line
        for line in text.splitlines()
        if any(needle in line.lower() for needle in needles)
    ]
    return "\n".join(lines)


def _rg_filter_file(path: Path, terms: list[str]) -> str | None:
    if not terms:
        return None
    command = ["rg", "-N", "-i", "-F"]
    for term in terms:
        command.extend(["-e", term])
    command.append(str(path))
    try:
        result = run_trusted(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode == 0:
        return result.stdout
    if result.returncode == 1:
        return ""
    return None


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

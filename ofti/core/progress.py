from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ofti.core.times import latest_time, processor_dirs

DEFAULT_STALE_AFTER_SECONDS = 120.0


def progress_evidence(
    case_dir: Path,
    *,
    process_live: bool,
    log_path: Path | None = None,
    paused: bool = False,
    now: float | None = None,
    stale_after: float = DEFAULT_STALE_AFTER_SECONDS,
) -> dict[str, Any]:
    """Return cheap, filesystem-backed progress evidence and stable reason codes."""
    timestamp = time.time() if now is None else now
    selected_log = log_path if log_path and log_path.is_file() else _newest_log(case_dir)
    log_mtime = _mtime(selected_log)
    selected_time = latest_time(case_dir)
    time_paths = _selected_time_paths(case_dir, selected_time)
    time_mtime = _latest_mtime(time_paths)
    latest_write = max(value for value in (log_mtime, time_mtime) if value is not None) if (
        log_mtime is not None or time_mtime is not None
    ) else None
    log_age = _age(timestamp, log_mtime)
    time_age = _age(timestamp, time_mtime)
    write_age = _age(timestamp, latest_write)
    reasons: list[str] = []
    if paused:
        reasons.append("PAUSED")
    elif not process_live:
        reasons.append("IDLE")
    else:
        if log_age is not None and log_age > stale_after:
            reasons.append("STALE_LOG")
        if write_age is None or write_age > stale_after:
            reasons.append("NO_PROGRESS")
    return {
        "process_live": process_live,
        "paused": paused,
        "log_path": str(selected_log) if selected_log else None,
        "log_age_seconds": log_age,
        "latest_time": selected_time,
        "latest_time_write_age_seconds": time_age,
        "latest_filesystem_write_age_seconds": write_age,
        "stale_after_seconds": stale_after,
        "reason_codes": reasons,
    }


def _newest_log(case_dir: Path) -> Path | None:
    logs = [path for path in case_dir.glob("log.*") if path.is_file()]
    return max(logs, key=lambda path: path.stat().st_mtime, default=None)


def _selected_time_paths(case_dir: Path, time_name: str) -> list[Path]:
    root = case_dir / time_name
    if root.is_dir():
        return [root]
    return [path / time_name for path in processor_dirs(case_dir) if (path / time_name).is_dir()]


def _latest_mtime(paths: list[Path]) -> float | None:
    values: list[float] = []
    for root in paths:
        root_mtime = _mtime(root)
        if root_mtime is not None:
            values.append(root_mtime)
        try:
            values.extend(
                stat.st_mtime
                for path in root.iterdir()
                if path.is_file() and (stat := path.stat())
            )
        except OSError:
            continue
    return max(values, default=None)


def _mtime(path: Path | None) -> float | None:
    if path is None:
        return None
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _age(now: float, mtime: float | None) -> float | None:
    return max(0.0, now - mtime) if mtime is not None else None

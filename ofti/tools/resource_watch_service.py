from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

_LOG_WARN_BYTES = 500 * 1024 * 1024
_TIME_DIR_WARN = 1000


def resource_watch_payload(case_path: Path) -> dict[str, Any]:
    logs = _log_rows(case_path)
    time_dirs = _count_time_dirs(case_path)
    processor_dirs = _count_prefix_dirs(case_path, "processor")
    free_bytes = shutil.disk_usage(case_path).free if case_path.exists() else None
    log_bytes = sum(int(row["bytes"]) for row in logs)
    risks: list[str] = []
    if log_bytes > _LOG_WARN_BYTES:
        risks.append("large solver logs")
    if time_dirs > _TIME_DIR_WARN:
        risks.append("many time directories")
    return {
        "case": str(case_path),
        "free_bytes": free_bytes,
        "time_dirs": time_dirs,
        "processor_dirs": processor_dirs,
        "log_bytes": log_bytes,
        "logs": logs[:10],
        "risk": ", ".join(risks) if risks else "low",
    }


def _log_rows(case_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        logs = sorted(case_path.glob("log.*"), key=lambda path: path.stat().st_size, reverse=True)
    except OSError:
        return rows
    for path in logs:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        rows.append({"log": path.name, "bytes": size, "size": _format_bytes(size)})
    return rows


def _count_time_dirs(case_path: Path) -> int:
    count = 0
    try:
        entries = list(case_path.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if entry.is_dir() and _is_time_name(entry.name):
            count += 1
    return count


def _count_prefix_dirs(case_path: Path, prefix: str) -> int:
    try:
        return sum(
            1
            for entry in case_path.iterdir()
            if entry.is_dir() and entry.name.startswith(prefix)
        )
    except OSError:
        return 0


def _is_time_name(name: str) -> bool:
    try:
        float(name)
    except ValueError:
        return False
    return True


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024
    return f"{value:.1f}TB"

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from ofti.core.entry_io import read_entry
from ofti.foam.openfoam import OpenFOAMError

_LOG_WARN_BYTES = 500 * 1024 * 1024
_TIME_DIR_WARN = 1000
_WRITE_INTERVAL_WARN = 100


def resource_watch_payload(case_path: Path) -> dict[str, Any]:
    logs = _log_rows(case_path)
    time_dirs = _count_time_dirs(case_path)
    processor_dirs = _count_prefix_dirs(case_path, "processor")
    free_bytes = shutil.disk_usage(case_path).free if case_path.exists() else None
    log_bytes = sum(int(row["bytes"]) for row in logs)
    write_settings = _control_dict_write_settings(case_path)
    risks: list[str] = []
    if log_bytes > _LOG_WARN_BYTES:
        risks.append("large solver logs")
    if time_dirs > _TIME_DIR_WARN:
        risks.append("many time directories")
    write_risk = _write_settings_risk(write_settings)
    if write_risk:
        risks.append(write_risk)
    return {
        "case": str(case_path),
        "free_bytes": free_bytes,
        "time_dirs": time_dirs,
        "processor_dirs": processor_dirs,
        "log_bytes": log_bytes,
        "logs": logs[:10],
        "risk": ", ".join(risks) if risks else "low",
        "write_settings": write_settings,
        "suggestions": _resource_suggestions(
            log_bytes=log_bytes,
            time_dirs=time_dirs,
            write_risk=write_risk,
        ),
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


def _control_dict_write_settings(case_path: Path) -> dict[str, Any]:
    control_dict = case_path / "system" / "controlDict"
    if not control_dict.is_file():
        return {"found": False}
    return {
        "found": True,
        "writeControl": _read_optional_entry(control_dict, "writeControl"),
        "writeInterval": _read_optional_entry(control_dict, "writeInterval"),
        "purgeWrite": _read_optional_entry(control_dict, "purgeWrite"),
    }


def _write_settings_risk(settings: dict[str, Any]) -> str | None:
    if not settings.get("found"):
        return None
    write_interval = _as_float(settings.get("writeInterval"))
    purge_write = _as_int(settings.get("purgeWrite"))
    write_control = str(settings.get("writeControl") or "").strip()
    if write_interval is not None and write_interval <= 0:
        return "invalid writeInterval"
    if (
        write_control in {"timeStep", "adjustableRunTime"}
        and write_interval is not None
        and write_interval <= _WRITE_INTERVAL_WARN
        and not purge_write
    ):
        return "frequent writes without purgeWrite"
    return None


def _resource_suggestions(
    *,
    log_bytes: int,
    time_dirs: int,
    write_risk: str | None,
) -> list[str]:
    suggestions: list[str] = []
    if write_risk:
        suggestions.append("Review system/controlDict writeInterval and purgeWrite.")
    if time_dirs > _TIME_DIR_WARN:
        suggestions.append("Consider pruning old time directories after preserving needed results.")
    if log_bytes > _LOG_WARN_BYTES:
        suggestions.append("Consider rotating or compressing old solver logs.")
    return suggestions


def _read_optional_entry(path: Path, key: str) -> str | None:
    try:
        return read_entry(path, key).strip().rstrip(";")
    except OpenFOAMError:
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            return None
        match = re.search(rf"(?m)^\s*{re.escape(key)}\s+([^;]+)\s*;", text)
        return match.group(1).strip() if match else None


def _as_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_int(value: object) -> int | None:
    try:
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


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

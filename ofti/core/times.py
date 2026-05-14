from __future__ import annotations

from pathlib import Path


def time_directories(case_path: Path) -> list[Path]:
    times: list[Path] = []
    for entry in case_path.iterdir():
        if not entry.is_dir():
            continue
        try:
            float(entry.name)
        except ValueError:
            continue
        times.append(entry)
    return sorted(times, key=lambda p: float(p.name))


def latest_time_scan(case_path: Path) -> str:
    """Return the latest numeric time directory without invoking OpenFOAM."""
    latest_value = 0.0
    found = False
    try:
        entries = case_path.iterdir()
    except OSError:
        return "0"
    for entry in entries:
        if not entry.is_dir():
            continue
        try:
            value = float(entry.name)
        except ValueError:
            continue
        if not found or value > latest_value:
            latest_value = value
            found = True
    return f"{latest_value:g}" if found else "0"


latest_time = latest_time_scan

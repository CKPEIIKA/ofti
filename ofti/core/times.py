from __future__ import annotations

from pathlib import Path

from ofti.foam.subprocess_utils import run_trusted


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


def latest_time(case_path: Path) -> str:
    try:
        result = run_trusted(
            ["foamListTimes", "-latestTime"],
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        result = None
    if result is not None and result.returncode == 0:
        value = (result.stdout or "").strip()
        if value:
            return value
    latest_value = 0.0
    found = False
    for entry in case_path.iterdir():
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

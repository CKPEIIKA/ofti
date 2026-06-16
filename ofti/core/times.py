from __future__ import annotations

import re
from pathlib import Path

from ofti.foam.subprocess_utils import run_trusted

PROCESSOR_RE = re.compile(r"^processor\d+$")


def _numeric_subdirs(directory: Path) -> list[Path]:
    times: list[Path] = []
    if not directory.is_dir():
        return times
    for entry in directory.iterdir():
        if not entry.is_dir():
            continue
        try:
            float(entry.name)
        except ValueError:
            continue
        times.append(entry)
    return sorted(times, key=lambda p: float(p.name))


def processor_dirs(case_path: Path) -> list[Path]:
    if not case_path.is_dir():
        return []
    procs = [
        entry
        for entry in case_path.iterdir()
        if entry.is_dir() and PROCESSOR_RE.match(entry.name)
    ]
    return sorted(procs, key=lambda p: int(p.name[len("processor") :]))


def time_directories(case_path: Path) -> list[Path]:
    # Merge root times with the first processor's times so decomposed cases
    # (where new times exist only under processor*/) are still discovered.
    by_name = {entry.name: entry for entry in _numeric_subdirs(case_path)}
    procs = processor_dirs(case_path)
    if procs:
        for entry in _numeric_subdirs(procs[0]):
            by_name.setdefault(entry.name, entry)
    return sorted(by_name.values(), key=lambda p: float(p.name))


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
    times = time_directories(case_path)
    return times[-1].name if times else "0"

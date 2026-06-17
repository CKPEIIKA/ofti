"""Pure, filesystem-only time-directory discovery (no process execution).

OpenFOAM-assisted ``latest_time`` (foamListTimes) lives in ``ofti.foam.times``;
this module stays in the pure core layer.
"""

from __future__ import annotations

import re
from pathlib import Path

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
    """Latest time directory by filesystem scan (root + ``processor*``)."""
    times = time_directories(case_path)
    return times[-1].name if times else "0"

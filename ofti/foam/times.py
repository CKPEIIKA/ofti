from __future__ import annotations

from pathlib import Path

from ofti.core.times import latest_time_scan
from ofti.foam.subprocess_utils import run_trusted


def latest_time(case_path: Path) -> str:
    """Return latest time using OpenFOAM when available, then filesystem scan."""
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
    return latest_time_scan(case_path)

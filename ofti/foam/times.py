"""OpenFOAM-assisted time discovery (the trusted-subprocess boundary).

Tries ``foamListTimes`` and falls back to the pure filesystem scan in
``ofti.core.times`` (which also understands decomposed ``processor*`` cases).
"""

from __future__ import annotations

from pathlib import Path

from ofti.core.times import latest_time as scan_latest_time
from ofti.foam.subprocess_utils import run_trusted


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
    return scan_latest_time(case_path)

from __future__ import annotations

import os
import shutil
from pathlib import Path

from ofti.foam.config import get_config
from ofti.foam.openfoam import OpenFOAMError
from ofti.foam.subprocess_utils import run_trusted


def ensure_environment() -> None:
    """
    Ensure OpenFOAM utilities are available.

    This checks for `foamDictionary` on PATH and raises a clear
    error if it is missing. The caller can catch this and show
    a user-friendly message in the TUI.
    """
    if shutil.which("foamDictionary") is None:
        raise OpenFOAMError.missing_foamdictionary()


def resolve_openfoam_bashrc() -> Path | None:
    cfg = get_config()
    candidates = [os.environ.get("OFTI_BASHRC"), cfg.openfoam_bashrc]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.is_file():
            return path
    return None


def wm_project_dir_from_bashrc(bashrc: Path) -> str | None:
    try:
        return str(bashrc.parent.parent)
    except OSError:
        return None


def auto_detect_bashrc_paths() -> list[Path]:
    roots = [
        Path("/opt"),
        Path("/usr/local"),
        Path("/Applications"),
        Path("/Volumes"),
        Path.home(),
    ]
    found: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            if "openfoam" not in entry.name.lower():
                continue
            bashrc = entry / "etc" / "bashrc"
            if bashrc.is_file() and bashrc not in seen:
                found.append(bashrc)
                seen.add(bashrc)
    return found


def with_bashrc(shell_cmd: str) -> str:
    bashrc = resolve_openfoam_bashrc()
    if not bashrc:
        return shell_cmd
    marker = f'. "{bashrc}"'
    if marker in shell_cmd:
        return shell_cmd
    return f"{marker}; {shell_cmd}"


def detect_openfoam_version() -> str:
    for env in ("WM_PROJECT_VERSION", "FOAM_VERSION"):
        version = os.environ.get(env)
        if version:
            return version
    try:
        result = run_trusted(
            ["foamVersion", "-short"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, FileNotFoundError):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    version = result.stdout.strip()
    return version or "unknown"

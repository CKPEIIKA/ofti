from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

from ofti.foam.config import get_config
from ofti.foam.openfoam import OpenFOAMError
from ofti.foam.subprocess_utils import run_trusted

_OPENFOAM_PROBE_COMMAND = "blockMesh"
_OPENFOAM_PROBE_TIMEOUT = 5.0


def ensure_environment() -> None:
    """Ensure OpenFOAM utilities are available.

    A normal Linux installation exposes ``foamVersion`` after its bashrc is
    sourced. macOS app installations instead expose a launcher that mounts a
    volume and creates the OpenFOAM PATH only inside a child shell, so probe a
    representative utility through the discovered environment as well.
    """
    if os.environ.get("WM_PROJECT_DIR"):
        return
    if os.environ.get("WM_PROJECT_VERSION") or os.environ.get("FOAM_VERSION"):
        return
    if shutil.which("foamVersion") is not None:
        return
    if resolve_openfoam_command(_OPENFOAM_PROBE_COMMAND) is not None:
        return
    raise OpenFOAMError.missing_openfoam_tools()


def resolve_openfoam_bashrc() -> Path | None:
    cfg = get_config()
    candidates = [os.environ.get("OFTI_BASHRC"), cfg.openfoam_bashrc]
    candidates.extend(str(path) for path in auto_detect_bashrc_paths())
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.is_file():
            return path
    return None


def wm_project_dir_from_bashrc(bashrc: Path) -> str | None:
    try:
        if bashrc.parent.name == "etc" and bashrc.parent.parent.name == "Resources":
            return None
        return str(bashrc.parent.parent)
    except OSError:
        return None


def auto_detect_bashrc_paths() -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for entry in _candidate_openfoam_dirs():
        bashrc = entry / "etc" / "bashrc"
        if bashrc.is_file() and bashrc not in seen:
            found.append(bashrc)
            seen.add(bashrc)
    return found


def _candidate_openfoam_dirs() -> list[Path]:
    entries: list[Path] = []
    project_dir = os.environ.get("WM_PROJECT_DIR")
    if project_dir:
        entries.append(Path(project_dir).expanduser())
    if launcher_dir := _openfoam_launcher_dir():
        entries.append(launcher_dir)
    for root in _openfoam_search_roots():
        entries.extend(_openfoam_dirs_in(root))

    unique: list[Path] = []
    seen: set[Path] = set()
    for entry in entries:
        if entry not in seen:
            unique.append(entry)
            seen.add(entry)
    return unique


def _openfoam_launcher_dir() -> Path | None:
    launcher = shutil.which("openfoam")
    if not launcher:
        return None
    try:
        launcher_path = Path(launcher).resolve()
    except OSError:
        launcher_path = Path(launcher)
    return launcher_path.parent.parent if launcher_path.parent.name == "etc" else None


def _openfoam_search_roots() -> list[Path]:
    return [
        Path("/opt"),
        Path("/usr/local"),
        Path("/Applications"),
        Path("/Volumes"),
        Path.home(),
    ]


def _openfoam_dirs_in(root: Path) -> list[Path]:
    if not root.exists():
        return []
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    candidates: list[Path] = []
    for entry in entries:
        if not entry.is_dir() or "openfoam" not in entry.name.lower():
            continue
        candidates.append(entry)
        if entry.name.lower().endswith(".app"):
            resources = entry / "Contents" / "Resources"
            if resources.is_dir():
                candidates.append(resources)
    return candidates


def with_bashrc(shell_cmd: str) -> str:
    bashrc = resolve_openfoam_bashrc()
    if not bashrc:
        return shell_cmd
    marker = f'. "{bashrc}"'
    if marker in shell_cmd:
        return shell_cmd
    return f"{marker}; {shell_cmd}"


def resolve_openfoam_command(command: str) -> str | None:
    """Resolve an OpenFOAM command from the active or discovered environment."""
    if not command or "/" in command:
        return command if command and Path(command).is_file() else None

    bashrc = resolve_openfoam_bashrc()
    if bashrc is not None:
        shell = f'. "{bashrc}"; command -v {shlex.quote(command)}'
        try:
            result = run_trusted(
                ["/bin/bash", "--noprofile", "--norc", "-c", shell],
                capture_output=True,
                text=True,
                check=False,
                timeout=_OPENFOAM_PROBE_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is not None and result.returncode == 0:
            resolved = result.stdout.strip().splitlines()
            if resolved:
                return resolved[-1]

    return shutil.which(command)


def detect_openfoam_version() -> str:
    for env in ("WM_PROJECT_VERSION", "FOAM_VERSION"):
        version = os.environ.get(env)
        if version:
            return version
    bashrc = resolve_openfoam_bashrc()
    if bashrc is not None:
        shell = (
            f'. "{bashrc}"; '
            "if command -v foamVersion >/dev/null 2>&1; then "
            "foamVersion -short; "
            'else printf "%s" "${WM_PROJECT_VERSION:-${FOAM_VERSION:-unknown}}"; fi'
        )
        args = ["/bin/bash", "--noprofile", "--norc", "-c", shell]
    else:
        args = ["foamVersion", "-short"]
    try:
        result = run_trusted(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=_OPENFOAM_PROBE_TIMEOUT,
        )
    except (OSError, FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    version = result.stdout.strip()
    return version or "unknown"

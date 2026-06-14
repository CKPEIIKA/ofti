from __future__ import annotations

import os
import shutil
import signal
import time
from dataclasses import dataclass
from pathlib import Path

from ofti.app.tool_screens.run import blockmesh_once
from ofti.core import entry_io
from ofti.tools.cli_tools import run


@dataclass(frozen=True)
class RealProfile:
    name: str
    source: Path
    solver: str | None = None
    tags: frozenset[str] = frozenset()


def parse_profile_specs(raw: str) -> list[RealProfile]:
    """Parse OFTI_REAL_PROFILES entries.

    Supported forms are intentionally shell-friendly:
    - /path/to/case
    - name=/path/to/case
    - name=/path/to/case;solver=simpleFoam;tags=serial,parallel
    """
    profiles: list[RealProfile] = []
    for item in raw.split(":"):
        text = item.strip()
        if not text:
            continue
        head, *parts = [part.strip() for part in text.split(";") if part.strip()]
        if "=" in head:
            name, path_text = head.split("=", 1)
        else:
            path_text = head
            name = Path(path_text).name
        options = _parse_options(parts)
        case = Path(path_text).expanduser().resolve()
        if not case.is_dir():
            continue
        tags = _parse_tags(options.get("tags", ""))
        profiles.append(
            RealProfile(
                name=(name.strip() or case.name),
                source=case,
                solver=options.get("solver") or None,
                tags=tags,
            ),
        )
    return profiles


def configured_profiles() -> list[RealProfile]:
    return parse_profile_specs(os.environ.get("OFTI_REAL_PROFILES", "").strip())


def copy_profiles(profiles: list[RealProfile], root: Path) -> list[tuple[RealProfile, Path]]:
    copied: list[tuple[RealProfile, Path]] = []
    for profile in profiles:
        destination = root / profile.name
        shutil.copytree(profile.source, destination)
        copied.append((profile, destination))
    return copied


def scenario_enabled(name: str) -> bool:
    raw = os.environ.get("OFTI_REAL_SCENARIOS", "").strip()
    if not raw:
        return True
    enabled = {part.strip() for part in raw.split(",") if part.strip()}
    return name in enabled or "all" in enabled


def resolve_solver(profile: RealProfile, case: Path) -> str | None:
    if profile.solver:
        return profile.solver
    try:
        display, command = run.solver_command(case)
    except ValueError:
        return None
    return command[0] if len(command) == 1 else display


def prepare_case(case: Path) -> None:
    zero_orig = case / "0.orig"
    zero_dir = case / "0"
    if zero_orig.is_dir() and not zero_dir.exists():
        shutil.copytree(zero_orig, zero_dir)
    poly_mesh = case / "constant" / "polyMesh"
    block_mesh_dict = case / "system" / "blockMeshDict"
    if poly_mesh.is_dir() or not block_mesh_dict.is_file():
        return
    ok, message = blockmesh_once(case)
    assert ok, message


def ensure_zero_orig(case: Path) -> None:
    zero = case / "0"
    zero_orig = case / "0.orig"
    if zero_orig.is_dir():
        return
    if zero.is_dir():
        shutil.copytree(zero, zero_orig)


def write_short_run(case: Path, solver: str) -> None:
    _write_run_control(
        case,
        solver,
        end_time=os.environ.get("OFTI_REAL_END_TIME", "1"),
        write_interval=os.environ.get("OFTI_REAL_WRITE_INTERVAL", "1"),
    )


def write_long_run(case: Path, solver: str) -> None:
    _write_run_control(
        case,
        solver,
        end_time=os.environ.get("OFTI_REAL_STOP_TEST_END_TIME", "100000"),
        write_interval=os.environ.get("OFTI_REAL_STOP_TEST_WRITE_INTERVAL", "100000"),
    )


def write_simple_decompose_dict(case: Path, *, ranks: int) -> None:
    system = case / "system"
    system.mkdir(exist_ok=True)
    (system / "decomposeParDict").write_text(
        "\n".join(
            [
                "FoamFile",
                "{",
                "    version 2.0;",
                "    format ascii;",
                "    class dictionary;",
                "    object decomposeParDict;",
                "}",
                f"numberOfSubdomains {ranks};",
                "method simple;",
                "simpleCoeffs",
                "{",
                f"    n ({ranks} 1 1);",
                "    delta 0.001;",
                "}",
                "",
            ],
        ),
        encoding="utf-8",
    )


def pid_running(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        pass
    else:
        if ") Z " in stat:
            return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def wait_pid_running(pid: int, *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pid_running(pid):
            return True
        time.sleep(0.05)
    return False


def wait_pids_gone(pids: list[int], *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(not pid_running(pid) for pid in pids):
            return True
        time.sleep(0.05)
    return all(not pid_running(pid) for pid in pids)


def kill_leftovers(pids: list[int]) -> None:
    for process_id in sorted(set(pids)):
        if pid_running(process_id):
            os.kill(process_id, signal.SIGKILL)


def _parse_options(parts: list[str]) -> dict[str, str]:
    options: dict[str, str] = {}
    for part in parts:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        options[key.strip()] = value.strip()
    return options


def _parse_tags(raw: str) -> frozenset[str]:
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def _write_run_control(case: Path, solver: str, *, end_time: str, write_interval: str) -> None:
    control = case / "system" / "controlDict"
    if not control.is_file():
        return
    entry_io.write_entry(control, "application", solver)
    entry_io.write_entry(control, "startFrom", "startTime")
    entry_io.write_entry(control, "startTime", "0")
    entry_io.write_entry(control, "stopAt", "endTime")
    entry_io.write_entry(control, "endTime", end_time)
    entry_io.write_entry(control, "writeInterval", write_interval)
    time.sleep(0.01)

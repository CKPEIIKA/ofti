from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from ofti.core.case import detect_solver
from ofti.foam.subprocess_utils import run_trusted
from ofti.tools import knife_service, watch_service
from ofti.tools.cli_tools import run as run_ops
from ofti.tools.helpers import with_bashrc


@dataclass(frozen=True)
class RealCaseProfile:
    name: str
    relative_path: str
    required_commands: tuple[str, ...]
    control_overrides: dict[str, str]
    pre_solver_commands: tuple[str, ...] = ()
    supports_parallel: bool = True
    supports_untracked_adoption: bool = True


REAL_CASE_PROFILES: tuple[RealCaseProfile, ...] = (
    RealCaseProfile(
        name="icoFoam-cavity",
        relative_path="incompressible/icoFoam/cavity/cavity",
        required_commands=("icoFoam",),
        control_overrides={"endTime": "100", "writeInterval": "1", "purgeWrite": "2"},
    ),
    RealCaseProfile(
        name="simpleFoam-pitzDaily",
        relative_path="incompressible/simpleFoam/pitzDaily",
        required_commands=("simpleFoam",),
        control_overrides={"endTime": "1000", "writeInterval": "100", "purgeWrite": "2"},
    ),
    RealCaseProfile(
        name="interFoam-damBreak",
        relative_path="multiphase/interFoam/laminar/damBreak/damBreak",
        required_commands=("interFoam", "setFields"),
        control_overrides={"endTime": "1", "writeInterval": "0.05", "purgeWrite": "2"},
        pre_solver_commands=("setFields",),
    ),
)


def selected_real_profiles() -> list[RealCaseProfile]:
    raw = os.environ.get(
        "OFTI_REAL_CASES",
        "icoFoam-cavity,simpleFoam-pitzDaily,interFoam-damBreak",
    )
    requested = {item.strip() for item in raw.split(",") if item.strip()}
    if not requested or "all" in requested:
        return list(REAL_CASE_PROFILES)
    by_name = {profile.name: profile for profile in REAL_CASE_PROFILES}
    unknown = sorted(requested.difference(by_name))
    if unknown:
        pytest.fail(f"Unknown OFTI_REAL_CASES profile(s): {', '.join(unknown)}")
    return [profile for profile in REAL_CASE_PROFILES if profile.name in requested]


def require_real_profile(profile: RealCaseProfile) -> Path:
    if os.environ.get("OFTI_ENABLE_REAL_CASE_TESTS") != "1":
        pytest.skip("Set OFTI_ENABLE_REAL_CASE_TESTS=1 to run real OpenFOAM tests.")
    missing = [
        cmd
        for cmd in (
            "pyFoamCloneCase.py",
            "blockMesh",
            "checkMesh",
            "decomposePar",
            "reconstructPar",
            "reconstructParMesh",
            "git",
            *profile.required_commands,
        )
        if shutil.which(cmd) is None
    ]
    if missing:
        pytest.skip(f"Missing real-case test tools: {', '.join(missing)}")
    template = _tutorial_template(profile)
    if template is None:
        pytest.skip(
            "Set OFTI_TOY_CASE_TEMPLATE, OFTI_REAL_CASE_ROOT, or FOAM_TUTORIALS "
            f"for profile {profile.name}.",
        )
    solver = detect_solver(template)
    if solver and solver != "unknown" and shutil.which(solver) is None:
        pytest.skip(f"Missing tutorial solver on PATH: {solver}")
    return template


def _tutorial_template(profile: RealCaseProfile) -> Path | None:
    explicit = os.environ.get("OFTI_TOY_CASE_TEMPLATE")
    if explicit and profile.name == "icoFoam-cavity":
        return Path(explicit).expanduser().resolve()
    roots = [
        os.environ.get("OFTI_REAL_CASE_ROOT"),
        os.environ.get("FOAM_TUTORIALS"),
        str(Path(os.environ["WM_PROJECT_DIR"]) / "tutorials")
        if os.environ.get("WM_PROJECT_DIR")
        else "",
    ]
    for root in roots:
        if not root:
            continue
        candidate = Path(root).expanduser() / profile.relative_path
        if (candidate / "system" / "controlDict").is_file():
            return candidate.resolve()
    return None


@dataclass
class RealOpenFOAMCase:
    profile: RealCaseProfile
    template: Path
    root: Path

    @property
    def case(self) -> Path:
        return self.root / f"ofti-real-{self.profile.name}"

    def clone(self) -> Path:
        result = run_trusted(
            ["pyFoamCloneCase.py", str(self.template), str(self.case)],
            check=False,
        )
        assert_command_ok(result, "pyFoamCloneCase.py")
        return self.case

    def initialize_change_tracking(self) -> None:
        assert_command_ok(run_trusted(["git", "-C", str(self.case), "init"], check=False), "git init")
        existing_roots = [
            root
            for root in ("system", "constant", "0", "0.orig")
            if (self.case / root).exists()
        ]
        assert_command_ok(
            run_trusted(["git", "-C", str(self.case), "add", "--", *existing_roots], check=False),
            "git add",
        )
        assert_command_ok(
            run_trusted(
                [
                    "git",
                    "-C",
                    str(self.case),
                    "-c",
                    "user.name=OFTI Real Test",
                    "-c",
                    "user.email=ofti-real-test@example.invalid",
                    "commit",
                    "-m",
                    "baseline",
                ],
                check=False,
            ),
            "git commit",
        )

    def configure_for_long_run(self) -> None:
        self.set_control(**self.profile.control_overrides)

    def restore_initial_dir(self) -> None:
        zero = self.case / "0"
        zero_orig = self.case / "0.orig"
        template_zero_orig = self.template / "0.orig"
        source = zero_orig if zero_orig.is_dir() else template_zero_orig
        if not zero.exists() and source.is_dir():
            shutil.copytree(source, zero)

    def set_control(self, **entries: str) -> None:
        for key, value in entries.items():
            payload = knife_service.set_entry_payload(
                self.case,
                "system/controlDict",
                key,
                value,
            )
            assert payload["ok"] is True

    def ensure_parallel_dict(self, ranks: int) -> None:
        path = self.case / "system" / "decomposeParDict"
        if path.is_file():
            assert knife_service.set_entry_payload(
                self.case,
                "system/decomposeParDict",
                "numberOfSubdomains",
                str(ranks),
            )["ok"] is True
            assert knife_service.set_entry_payload(
                self.case,
                "system/decomposeParDict",
                "method",
                "scotch",
            )["ok"] is True
            return
        path.write_text(
            "\n".join(
                [
                    "FoamFile",
                    "{",
                    "    version     2.0;",
                    "    format      ascii;",
                    "    class       dictionary;",
                    "    object      decomposeParDict;",
                    "}",
                    f"numberOfSubdomains {ranks};",
                    "method scotch;",
                    "",
                ],
            ),
            encoding="utf-8",
        )

    def run_tool(self, name: str, command: list[str]) -> None:
        result = run_ops.execute_case_command(
            self.case,
            name,
            command,
            background=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout

    def run_block_mesh(self) -> None:
        self.run_tool("blockMesh", ["blockMesh"])

    def run_check_mesh(self) -> None:
        self.run_tool("checkMesh", ["checkMesh"])

    def start_tracked_solver(self, *, parallel: int = 0) -> int:
        display, command = run_ops.solver_command(self.case, parallel=parallel)
        result = run_ops.execute_solver_case_command(
            self.case,
            display,
            command,
            parallel=parallel,
            background=True,
        )
        assert result.pid is not None
        return int(result.pid)

    def start_untracked_solver(self) -> subprocess.Popen[str]:
        solver = detect_solver(self.case)
        assert solver is not None and solver != "unknown"
        log_path = self.case / f"log.{solver}.untracked"
        handle = log_path.open("a", encoding="utf-8", errors="ignore")
        try:
            return subprocess.Popen(  # noqa: S603 - opt-in test launches a trusted tutorial solver.
                ["/bin/bash", "--noprofile", "--norc", "-c", with_bashrc(solver)],
                cwd=self.case,
                stdout=handle,
                stderr=handle,
                text=True,
                start_new_session=True,
            )
        finally:
            handle.close()

    def stop_all_solvers(self) -> dict[str, Any]:
        return knife_service.stop_payload(self.case, all_jobs=True, signal_name="TERM")

    def cleanup(self) -> None:
        with suppress(Exception):
            self.stop_all_solvers()
        for job in watch_service.jobs_payload(self.case, include_all=True).get("jobs", []):
            pid = as_positive_int(job.get("pid"))
            if pid:
                with suppress(OSError):
                    os.kill(pid, signal.SIGTERM)


def make_real_case(profile: RealCaseProfile, tmp_path: Path) -> RealOpenFOAMCase:
    real_case = RealOpenFOAMCase(profile, require_real_profile(profile), tmp_path)
    real_case.clone()
    real_case.restore_initial_dir()
    real_case.configure_for_long_run()
    real_case.run_block_mesh()
    for command in profile.pre_solver_commands:
        real_case.run_tool(command, [command])
    real_case.run_check_mesh()
    real_case.initialize_change_tracking()
    return real_case


def assert_command_ok(result: Any, label: str) -> None:
    assert int(result.returncode) == 0, f"{label} failed:\n{result.stderr or result.stdout}"


def wait_until(
    check: Callable[[], bool],
    *,
    timeout: float = 12.0,
    description: str = "real OpenFOAM case state",
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {description}")


def wait_payload(
    snapshot: Callable[[], dict[str, Any]],
    accept: Callable[[dict[str, Any]], bool],
    *,
    timeout: float = 12.0,
    description: str,
) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        latest = snapshot()
        if accept(latest):
            return latest
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {description}: {latest}")


def running_jobs(case: Path) -> int:
    return int(knife_service.current_payload(case, live=True).get("jobs_running", 0))


def tracked_solver_jobs(case: Path) -> int:
    return int(watch_service.jobs_payload(case, include_all=False, kind="solver")["count"])


def as_positive_int(value: object) -> int | None:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None

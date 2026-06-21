from __future__ import annotations

import os
import shutil
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
from tests.real_openfoam_support import kill_leftovers


@dataclass(frozen=True)
class TutorialProfile:
    name: str
    relative_path: str
    required_commands: tuple[str, ...]
    control_overrides: dict[str, str]
    pre_solver_commands: tuple[str, ...] = ()
    supports_parallel: bool = True


TUTORIAL_PROFILES: tuple[TutorialProfile, ...] = (
    TutorialProfile(
        name="icoFoam-cavity",
        relative_path="incompressible/icoFoam/cavity/cavity",
        required_commands=("icoFoam",),
        control_overrides={"endTime": "100", "writeInterval": "1", "purgeWrite": "2"},
    ),
    TutorialProfile(
        name="simpleFoam-pitzDaily",
        relative_path="incompressible/simpleFoam/pitzDaily",
        required_commands=("simpleFoam",),
        control_overrides={"endTime": "1000", "writeInterval": "100", "purgeWrite": "2"},
    ),
    TutorialProfile(
        name="interFoam-damBreak",
        relative_path="multiphase/interFoam/laminar/damBreak/damBreak",
        required_commands=("interFoam", "setFields"),
        control_overrides={"endTime": "1", "writeInterval": "0.05", "purgeWrite": "2"},
        pre_solver_commands=("setFields",),
    ),
)


def selected_tutorial_profiles() -> list[TutorialProfile]:
    raw = os.environ.get("OFTI_REAL_CASES", "icoFoam-cavity")
    requested = {item.strip() for item in raw.split(",") if item.strip()}
    if not requested or "all" in requested:
        return list(TUTORIAL_PROFILES)
    by_name = {profile.name: profile for profile in TUTORIAL_PROFILES}
    unknown = sorted(requested.difference(by_name))
    if unknown:
        pytest.fail(f"Unknown OFTI_REAL_CASES profile(s): {', '.join(unknown)}")
    return [profile for profile in TUTORIAL_PROFILES if profile.name in requested]


def require_tutorial_template(profile: TutorialProfile) -> Path:
    if os.environ.get("OFTI_ENABLE_REAL_CASE_TESTS") != "1":
        pytest.skip("Set OFTI_ENABLE_REAL_CASE_TESTS=1 to run tutorial OpenFOAM tests.")
    missing = [cmd for cmd in ("blockMesh", "checkMesh", *profile.required_commands) if shutil.which(cmd) is None]
    if missing:
        pytest.skip(f"Missing tutorial test tools: {', '.join(missing)}")
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


def _tutorial_template(profile: TutorialProfile) -> Path | None:
    explicit = os.environ.get("OFTI_TOY_CASE_TEMPLATE")
    if explicit and profile.name == "icoFoam-cavity":
        candidate = Path(explicit).expanduser().resolve()
        return candidate if (candidate / "system" / "controlDict").is_file() else None
    roots = [
        os.environ.get("OFTI_REAL_CASE_ROOT"),
        os.environ.get("FOAM_TUTORIALS"),
        str(Path(os.environ["WM_PROJECT_DIR"]) / "tutorials") if os.environ.get("WM_PROJECT_DIR") else "",
    ]
    for root in roots:
        if not root:
            continue
        candidate = Path(root).expanduser() / profile.relative_path
        if (candidate / "system" / "controlDict").is_file():
            return candidate.resolve()
    # Fall back to the runnable cavity bundled in the repo so the real suite works
    # out of the box when OpenFOAM is installed but tutorials are not shipped.
    if profile.name == "icoFoam-cavity":
        bundled = Path(__file__).resolve().parents[1] / "examples" / "cavity"
        if (bundled / "system" / "controlDict").is_file():
            return bundled.resolve()
    return None


@dataclass
class RealTutorialCase:
    profile: TutorialProfile
    template: Path
    root: Path

    @property
    def case(self) -> Path:
        return self.root / f"ofti-real-{self.profile.name}"

    def clone(self) -> Path:
        if shutil.which("pyFoamCloneCase.py") is not None:
            result = run_trusted(["pyFoamCloneCase.py", str(self.template), str(self.case)], check=False)
            assert_command_ok(result, "pyFoamCloneCase.py")
        else:
            shutil.copytree(self.template, self.case, symlinks=True)
        return self.case

    def restore_initial_dir(self) -> None:
        zero = self.case / "0"
        zero_orig = self.case / "0.orig"
        template_zero_orig = self.template / "0.orig"
        source = zero_orig if zero_orig.is_dir() else template_zero_orig
        if not zero.exists() and source.is_dir():
            shutil.copytree(source, zero)

    def configure_for_long_run(self) -> None:
        for key, value in self.profile.control_overrides.items():
            assert knife_service.set_entry_payload(self.case, "system/controlDict", key, value)["ok"] is True

    def ensure_parallel_dict(self, ranks: int) -> None:
        path = self.case / "system" / "decomposeParDict"
        if path.is_file():
            assert knife_service.set_entry_payload(
                self.case,
                "system/decomposeParDict",
                "numberOfSubdomains",
                str(ranks),
            )["ok"] is True
            return
        path.write_text(
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
                    "method scotch;",
                    "",
                ],
            ),
            encoding="utf-8",
        )

    def run_tool(self, name: str, command: list[str]) -> None:
        result = run_ops.execute_case_command(self.case, name, command, background=False)
        assert_command_ok(result, name)

    def start_solver(self, *, parallel: int = 0) -> int:
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

    def stop_all_solvers(self) -> dict[str, Any]:
        return knife_service.stop_payload(self.case, all_jobs=True, signal_name="TERM")

    def cleanup(self) -> None:
        with suppress(Exception):
            self.stop_all_solvers()
        pids: list[int] = []
        for job in watch_service.jobs_payload(self.case, include_all=True).get("jobs", []):
            pid = _as_positive_int(job.get("pid"))
            if pid:
                pids.append(pid)
        kill_leftovers(pids)


def make_tutorial_case(profile: TutorialProfile, tmp_path: Path) -> RealTutorialCase:
    real_case = RealTutorialCase(profile, require_tutorial_template(profile), tmp_path)
    real_case.clone()
    real_case.restore_initial_dir()
    real_case.configure_for_long_run()
    real_case.run_tool("blockMesh", ["blockMesh"])
    for command in profile.pre_solver_commands:
        real_case.run_tool(command, [command])
    real_case.run_tool("checkMesh", ["checkMesh"])
    return real_case


def wait_until(check: Callable[[], bool], *, timeout: float = 12.0, description: str = "real tutorial state") -> None:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {description}")


def running_jobs(case: Path) -> int:
    return int(knife_service.current_payload(case, live=True).get("jobs_running", 0))


def assert_command_ok(result: Any, label: str) -> None:
    assert int(result.returncode) == 0, f"{label} failed:\n{result.stderr or result.stdout}"


def _as_positive_int(value: object) -> int | None:
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast
from unittest import mock

from ofti.tools.solver import _tail_process_log, run_current_solver_live


class FakeScreen:
    def __init__(self, keys) -> None:
        self._keys = list(keys)
        self.lines: list[str] = []
        self.height = 24
        self.width = 80
        self._timeout = None

    def clear(self) -> None:
        self.lines.clear()

    def erase(self) -> None:
        self.lines.clear()

    def getmaxyx(self):
        return (self.height, self.width)

    def getyx(self):
        return (0, 0)

    def addstr(self, *args):
        text = args[-1]
        self.lines.append(str(text))

    def move(self, y, x):
        pass

    def attron(self, *args, **kwargs):
        pass

    def attroff(self, *args, **kwargs):
        pass

    def refresh(self) -> None:
        pass

    def timeout(self, value: int) -> None:
        self._timeout = value

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("h")


class FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.waited = False

    def poll(self):
        return None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> None:
        _ = timeout
        self.waited = True


def _write_control_dict(case_dir: Path, solver: str = "simpleFoam") -> None:
    control = case_dir / "system" / "controlDict"
    control.parent.mkdir(parents=True, exist_ok=True)
    control.write_text(f"application {solver};\n")


def _write_zero_fields(case_dir: Path) -> None:
    zero_dir = case_dir / "0"
    zero_dir.mkdir(exist_ok=True)
    (zero_dir / "U").write_text("internalField uniform (0 0 0);\n")
    (zero_dir / "p").write_text("internalField uniform 0;\n")


def test_run_current_solver_live_rerun_declines(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    _write_control_dict(case_dir)
    _write_zero_fields(case_dir)
    log_path = case_dir / "log.simpleFoam"
    log_path.write_text("old log")

    screen = FakeScreen(keys=[ord("n")])
    monkeypatch.setattr("ofti.tools.solver.read_entry", lambda *_args, **_kw: "simpleFoam;")
    monkeypatch.setattr("ofti.tools.solver.require_wm_project_dir", lambda *_args, **_kw: None)
    monkeypatch.setattr("ofti.tools.solver.resolve_openfoam_bashrc", lambda: None)
    runner = mock.Mock()
    monkeypatch.setattr("ofti.tools.solver._run_solver_live_cmd", runner)

    run_current_solver_live(screen, case_dir)

    assert log_path.exists()
    assert not runner.called


def test_run_current_solver_live_rerun_accepts(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    _write_control_dict(case_dir)
    _write_zero_fields(case_dir)
    log_path = case_dir / "log.simpleFoam"
    log_path.write_text("old log")

    screen = FakeScreen(keys=[ord("y")])
    monkeypatch.setattr("ofti.tools.solver.read_entry", lambda *_args, **_kw: "simpleFoam;")
    monkeypatch.setattr("ofti.tools.solver.require_wm_project_dir", lambda *_args, **_kw: None)
    monkeypatch.setattr("ofti.tools.solver.resolve_openfoam_bashrc", lambda: None)
    runner = mock.Mock()
    monkeypatch.setattr("ofti.tools.solver._run_solver_live_cmd", runner)

    run_current_solver_live(screen, case_dir)

    assert runner.called
    assert log_path.exists()
    assert log_path.read_text() == ""


def test_run_current_solver_live_skips_runfunctions(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    _write_control_dict(case_dir)
    _write_zero_fields(case_dir)

    screen = FakeScreen(keys=[ord("h")])
    monkeypatch.setenv("WM_PROJECT_DIR", "/WM")
    monkeypatch.setattr("ofti.tools.solver.read_entry", lambda *_args, **_kw: "simpleFoam;")
    monkeypatch.setattr("ofti.tools.solver.resolve_openfoam_bashrc", lambda: None)
    runner = mock.Mock()
    monkeypatch.setattr("ofti.tools.solver._run_solver_live_cmd", runner)

    run_current_solver_live(screen, case_dir)

    assert runner.called


def test_tail_process_log_stops_on_back(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    log_path = case_dir / "log.simpleFoam"
    log_path.write_text("Time = 0.1\n")
    screen = FakeScreen(keys=[ord("h")])
    process = FakeProcess()

    _tail_process_log(
        screen,
        case_dir,
        "simpleFoam",
        cast(subprocess.Popen[str], process),
        log_path,
        None,
    )

    assert process.terminated
    assert process.waited


def test_tail_process_log_renders_residuals(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    log_path = case_dir / "log.simpleFoam"
    log_path.write_text(
        "\n".join(
            [
                "Time = 0.1",
                "Solving for p, Initial residual = 0.01, Final residual = 0.001, No Iterations 2",
            ],
        ),
    )
    screen = FakeScreen(keys=[ord("h")])
    process = FakeProcess()

    _tail_process_log(
        screen,
        case_dir,
        "simpleFoam",
        cast(subprocess.Popen[str], process),
        log_path,
        None,
    )

    joined = "\n".join(screen.lines)
    assert "Res" in joined

"""Tool menu behavior and integration points."""

from pathlib import Path
from unittest import mock

from ofti.tools.cleaning_ops import clean_time_directories, remove_all_logs
from ofti.tools.diagnostics import diagnostics_screen
from ofti.tools.menus import TOOLS_SPECIAL_HINTS
from ofti.tools.runner import load_postprocessing_presets
from ofti.tools.shell_tools import run_shell_script_screen
from ofti.tools.solver import run_current_solver


class FakeScreen:
    def __init__(self, keys, string_inputs=None) -> None:
        self._keys = list(keys)
        self._strings = [s.encode() for s in (string_inputs or [])]
        self.lines: list[str] = []
        self.height = 24
        self.width = 80

    def clear(self) -> None:
        self.lines.clear()

    def erase(self) -> None:
        self.lines.clear()

    def getmaxyx(self):
        return (self.height, self.width)

    def addstr(self, *args):
        text = args[-1]
        self.lines.append(str(text))

    def move(self, y, x):
        # Cursor movement is ignored in tests.
        pass

    def attron(self, *args, **kwargs):
        # Color attributes are ignored in tests.
        pass

    def attroff(self, *args, **kwargs):
        # Color attributes are ignored in tests.
        pass

    def refresh(self) -> None:
        pass

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        # Default to 'h' (back) to avoid QuitAppError.
        return ord("h")

    def getstr(self):
        if self._strings:
            return self._strings.pop(0)
        return b""


def test_run_shell_script_screen_runs_script_and_shows_output(tmp_path: Path) -> None:
    """Render output from a selected shell script."""
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    script = case_dir / "hello.sh"
    script.write_text("#!/bin/sh\necho hello-from-script\n")

    # Select first script, then 'q' to exit viewer.
    screen = FakeScreen(keys=[ord("\n"), ord("h")])

    run_shell_script_screen(screen, case_dir)

    # Expect the command and output to have been written to the screen.
    joined = "\n".join(screen.lines)
    assert "sh hello.sh" in joined
    assert "hello-from-script" in joined


def test_run_shell_script_screen_handles_no_scripts(tmp_path: Path) -> None:
    """Warn when no scripts exist in the case directory."""
    case_dir = tmp_path / "case"
    case_dir.mkdir()

    screen = FakeScreen(keys=[ord("h")])

    run_shell_script_screen(screen, case_dir)

    joined = "\n".join(screen.lines)
    assert "No *.sh scripts found in case directory." in joined


def test_tools_menu_special_hints_present() -> None:
    assert len(TOOLS_SPECIAL_HINTS) >= 5


def test_diagnostics_screen_runs_selected_tool(tmp_path: Path) -> None:
    """Run a diagnostics command and show its output."""
    case_dir = tmp_path / "case"
    case_dir.mkdir()

    # Select first tool entry (skip case report/doctor/compare), then exit viewer.
    screen = FakeScreen(keys=[ord("j"), ord("j"), ord("j"), ord("\n"), ord("h")])

    completed = mock.Mock()
    completed.returncode = 0
    completed.stdout = "ok\n"
    completed.stderr = ""

    with mock.patch("ofti.tools.diagnostics.run_trusted", return_value=completed) as run:
        diagnostics_screen(screen, case_dir)

    # Ensure a diagnostics command was invoked.
    assert run.called
    # And that output was sent to the viewer.
    joined = "\n".join(screen.lines)
    assert "stdout:" in joined
    assert "ok" in joined


def test_run_current_solver_uses_runfunctions(tmp_path: Path) -> None:
    """Run solver directly when configured without RunFunctions."""
    case_dir = tmp_path / "case"
    control = case_dir / "system" / "controlDict"
    control.parent.mkdir(parents=True)
    control.write_text("application simpleFoam;\n")
    zero_dir = case_dir / "0"
    zero_dir.mkdir()
    (zero_dir / "U").write_text("internalField uniform (0 0 0);\n")
    (zero_dir / "p").write_text("internalField uniform 0;\n")
    screen = FakeScreen(keys=[ord("\n"), ord("h")])

    completed = mock.Mock()
    completed.returncode = 0
    completed.stdout = "ok\n"
    completed.stderr = ""

    with (
            mock.patch("ofti.core.solver_checks.read_entry", return_value="simpleFoam;"),
        mock.patch("ofti.tools.runner.run_trusted", return_value=completed) as run,
    ):
        run_current_solver(screen, case_dir)

    assert run.called
    assert run.call_args[0][0][0] == "simpleFoam"


def test_remove_all_logs_uses_cleanfunctions(tmp_path: Path, monkeypatch) -> None:
    """Clean logs through the OpenFOAM helper script."""
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    screen = FakeScreen(keys=[ord("h")])

    completed = mock.Mock()
    completed.returncode = 0
    completed.stdout = ""
    completed.stderr = ""

    monkeypatch.setenv("WM_PROJECT_DIR", "/WM")
    with mock.patch("ofti.tools.runner.run_trusted", return_value=completed) as run:
        remove_all_logs(screen, case_dir)

    assert run.called
    shell_cmd = run.call_args[0][0][-1]
    assert "CleanFunctions" in shell_cmd
    assert "cleanApplicationLogs" in shell_cmd


def test_clean_time_directories(tmp_path: Path, monkeypatch) -> None:
    """Clean time directories via CleanFunctions."""
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    screen = FakeScreen(keys=[ord("h")])

    completed = mock.Mock()
    completed.returncode = 0
    completed.stdout = ""
    completed.stderr = ""

    monkeypatch.setenv("WM_PROJECT_DIR", "/WM")
    with mock.patch("ofti.tools.runner.run_trusted", return_value=completed) as run:
        clean_time_directories(screen, case_dir)

    assert run.called
    shell_cmd = run.call_args[0][0][-1]
    assert "CleanFunctions" in shell_cmd
    assert "cleanTimeDirectories" in shell_cmd


def test_load_postprocessing_presets(tmp_path: Path) -> None:
    """Parse post-processing preset config entries."""
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    cfg = case_dir / "ofti.postprocessing"
    cfg.write_text(
        """
        # Sample post-processing command
        foamToVTK: foamToVTK -latestTime
        """,
    )

    presets = load_postprocessing_presets(case_dir)

    assert presets == [("foamToVTK", ["foamToVTK", "-latestTime"])]

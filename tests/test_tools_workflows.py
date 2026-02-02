"""Tool workflow tests to raise coverage over tool helpers."""

import curses
from pathlib import Path
from typing import Any

from ofti.core.times import latest_time
from ofti.tools.menus import run_tool_by_name
from ofti.tools.runner import (
    _normalize_tool_name,
    _record_last_tool,
    _record_tool_status,
    last_tool_status_line,
    list_tool_commands,
    time,
)
from ofti.tools.shell_tools import rerun_last_tool
from ofti.tools.tool_dicts_foamcalc import foam_calc_prompt
from ofti.tools.tool_dicts_postprocess import post_process_prompt


class FakeScreen:
    def __init__(self, keys=None, string_inputs=None) -> None:
        self._keys = list(keys or [])
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

    def addstr(self, *args) -> None:
        self.lines.append(str(args[-1]))

    def move(self, *args, **kwargs) -> None:
        pass

    def clrtoeol(self) -> None:
        pass

    def attron(self, *args, **kwargs) -> None:
        pass

    def attroff(self, *args, **kwargs) -> None:
        pass

    def refresh(self) -> None:
        pass

    def derwin(self, *_args, **_kwargs):
        return self

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("h")

    def getstr(self):
        if self._strings:
            return self._strings.pop(0)
        return b""


def test_normalize_tool_name() -> None:
    assert _normalize_tool_name("  FoamCalc  ") == "foamcalc"
    assert _normalize_tool_name("post:sample") == "post:sample"


def test_list_tool_commands_includes_presets(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "ofti.tools").write_text("custom: echo ok\n")
    (case_dir / "ofti.postprocessing").write_text("postA: postProcess -funcs\n")

    commands = list_tool_commands(case_dir)

    assert "custom" in commands
    assert "posta" in commands
    assert "post:posta" in commands


def test_run_tool_by_name_dispatches_simple_tool(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    screen = FakeScreen()
    called: list[str] = []

    def fake_run_blockmesh(_stdscr, _case):
        called.append("blockMesh")

    monkeypatch.setattr("ofti.tools.run.run_blockmesh", fake_run_blockmesh)

    assert run_tool_by_name(screen, case_dir, "blockMesh") is True
    assert called == ["blockMesh"]


def test_rerun_last_tool_replays_shell(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    screen = FakeScreen(keys=[ord("h")])
    recorded: list[str] = []

    def fake_run_shell(_stdscr, _case, _name, shell_cmd):
        recorded.append(shell_cmd)

    monkeypatch.setattr("ofti.tools.shell_tools._run_shell_tool", fake_run_shell)

    _record_last_tool("demo", "shell", "echo hi")
    rerun_last_tool(screen, case_dir)

    assert recorded == ["echo hi"]


def test_post_process_prompt_runs_default_args(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    screen = FakeScreen(keys=[ord("h")], string_inputs=[""])

    monkeypatch.setattr(curses, "echo", lambda: None)
    monkeypatch.setattr(curses, "noecho", lambda: None)

    def fake_run_simple(_stdscr, _case, name, _cmd):
        screen.addstr(name)

    monkeypatch.setattr("ofti.tools.tool_dicts_postprocess._run_simple_tool", fake_run_simple)

    post_process_prompt(screen, case_dir)

    joined = "\n".join(screen.lines)
    assert "postProcess" in joined


def test_foam_calc_prompt_runs_args(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    screen = FakeScreen(keys=[ord("h")], string_inputs=["components U -latestTime"])

    monkeypatch.setattr(curses, "echo", lambda: None)
    monkeypatch.setattr(curses, "noecho", lambda: None)

    def fake_run_simple(_stdscr, _case, name, _cmd):
        screen.addstr(name)

    monkeypatch.setattr("ofti.tools.tool_dicts_foamcalc._run_simple_tool", fake_run_simple)

    foam_calc_prompt(screen, case_dir)

    joined = "\n".join(screen.lines)
    assert "foamCalc" in joined


def test_last_tool_status_line(monkeypatch) -> None:
    _record_tool_status("blockMesh", "exit 0")
    assert last_tool_status_line() == "last tool: blockMesh exit 0"
    base = time.time()
    monkeypatch.setattr(time, "time", lambda: base + 20)
    assert last_tool_status_line() is None


def test_latest_time_picks_max_directory(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    for name in ("0", "0.5", "2", "postProcessing"):
        (case_dir / name).mkdir()

    assert latest_time(case_dir) == "2"


def test_write_stub_dict_creates_file(tmp_path: Path) -> None:
    path = tmp_path / "topoSetDict"
    from ofti.core.tool_dicts_service import _write_stub_dict

    _write_stub_dict(path, "topoSet")

    text = path.read_text()
    assert "FoamFile" in text


def test_run_tool_by_name_background_uses_job_registry(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    screen = FakeScreen()
    started: list[tuple[str, list[str]]] = []

    def fake_background(stdscr: Any, path: Path, name: str, cmd: list[str]) -> None:
        started.append((name, list(cmd)))

    monkeypatch.setattr(
        "ofti.tools.job_control.start_tool_background",
        fake_background,
    )

    assert run_tool_by_name(screen, case_dir, "blockMesh", background=True) is True
    assert started == [("blockmesh", ["blockMesh"])]

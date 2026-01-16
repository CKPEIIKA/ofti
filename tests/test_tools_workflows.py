"""Tool workflow tests to raise coverage over tool helpers."""

from pathlib import Path
from unittest import mock

import of_tui.tools as tools


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

    def derwin(self, *args, **kwargs):
        return self

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("q")

    def getstr(self):
        if self._strings:
            return self._strings.pop(0)
        return b""


def test_normalize_tool_name() -> None:
    assert tools._normalize_tool_name("  FoamCalc  ") == "foamcalc"
    assert tools._normalize_tool_name("post:sample") == "post:sample"


def test_list_tool_commands_includes_presets(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "of_tui.tools").write_text("custom: echo ok\n")
    (case_dir / "of_tui.postprocessing").write_text("postA: postProcess -funcs\n")

    commands = tools.list_tool_commands(case_dir)

    assert "custom" in commands
    assert "posta" in commands
    assert "post:posta" in commands


def test_run_tool_by_name_dispatches_simple_tool(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    screen = FakeScreen()
    called: list[tuple[str, list[str]]] = []

    def fake_run_simple(_stdscr, _case, name, cmd):
        called.append((name, cmd))

    monkeypatch.setattr(tools, "_run_simple_tool", fake_run_simple)

    assert tools.run_tool_by_name(screen, case_dir, "blockMesh") is True
    assert called and called[0][0] == "blockMesh"


def test_rerun_last_tool_replays_shell(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    screen = FakeScreen(keys=[ord("q")])
    recorded: list[str] = []

    def fake_run_shell(_stdscr, _case, name, shell_cmd):
        recorded.append(shell_cmd)

    monkeypatch.setattr(tools, "_run_shell_tool", fake_run_shell)

    tools._record_last_tool("demo", "shell", "echo hi")
    tools.rerun_last_tool(screen, case_dir)

    assert recorded == ["echo hi"]


def test_post_process_prompt_runs_default_args(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    screen = FakeScreen(keys=[ord("q")], string_inputs=[""])

    completed = mock.Mock()
    completed.returncode = 0
    completed.stdout = "ok\n"
    completed.stderr = ""

    monkeypatch.setattr(tools.curses, "echo", lambda: None)
    monkeypatch.setattr(tools.curses, "noecho", lambda: None)
    monkeypatch.setattr(tools.subprocess, "run", lambda *args, **kwargs: completed)

    tools.post_process_prompt(screen, case_dir)

    joined = "\n".join(screen.lines)
    assert "postProcess" in joined


def test_foam_calc_prompt_runs_args(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    screen = FakeScreen(keys=[ord("q")], string_inputs=["components U -latestTime"])

    completed = mock.Mock()
    completed.returncode = 0
    completed.stdout = "ok\n"
    completed.stderr = ""

    monkeypatch.setattr(tools.curses, "echo", lambda: None)
    monkeypatch.setattr(tools.curses, "noecho", lambda: None)
    monkeypatch.setattr(tools.subprocess, "run", lambda *args, **kwargs: completed)

    tools.foam_calc_prompt(screen, case_dir)

    joined = "\n".join(screen.lines)
    assert "foamCalc" in joined


def test_topo_set_prompt_runs_default(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    screen = FakeScreen(keys=[ord("q")], string_inputs=[""])

    completed = mock.Mock()
    completed.returncode = 0
    completed.stdout = "ok\n"
    completed.stderr = ""

    monkeypatch.setattr(tools.curses, "echo", lambda: None)
    monkeypatch.setattr(tools.curses, "noecho", lambda: None)
    monkeypatch.setattr(tools.subprocess, "run", lambda *args, **kwargs: completed)

    tools.topo_set_prompt(screen, case_dir)

    joined = "\n".join(screen.lines)
    assert "topoSet" in joined


def test_tool_dicts_screen_generates_and_opens(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    screen = FakeScreen(keys=[ord("\n"), ord("y"), ord("q")])

    completed = mock.Mock()
    completed.returncode = 0
    completed.stdout = "FoamFile\n{\n}\n"
    completed.stderr = ""

    monkeypatch.setattr(tools.subprocess, "run", lambda *args, **kwargs: completed)

    tools.tool_dicts_screen(screen, case_dir)

    target = case_dir / "system" / "postProcessDict"
    assert target.is_file()


def test_latest_time_picks_max_directory(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    for name in ("0", "0.5", "2", "postProcessing"):
        (case_dir / name).mkdir()

    assert tools._latest_time(case_dir) == "2"


def test_write_stub_dict_creates_file(tmp_path: Path) -> None:
    path = tmp_path / "topoSetDict"
    tools._write_stub_dict(path, "topoSet")

    text = path.read_text()
    assert "FoamFile" in text

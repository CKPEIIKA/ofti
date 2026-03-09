from __future__ import annotations

import types
from pathlib import Path

import pytest

from ofti.foam.exceptions import QuitAppError
from ofti.tools import runner


class _Screen:
    def __init__(self, keys: list[int] | None = None) -> None:
        self._keys = list(keys or [ord("h")])
        self.lines: list[str] = []

    def clear(self) -> None:
        self.lines.clear()

    def addstr(self, *args: object) -> None:
        self.lines.append(str(args[-1]))

    def refresh(self) -> None:
        return None

    def getmaxyx(self) -> tuple[int, int]:
        return (24, 100)

    def attron(self, *_args: object) -> None:
        return None

    def attroff(self, *_args: object) -> None:
        return None

    def move(self, *_args: object) -> None:
        return None

    def clrtoeol(self) -> None:
        return None

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("h")


def test_runner_no_foam_and_status_helpers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("OFTI_NO_FOAM", "1")
    assert runner._no_foam_active() is True
    assert runner._no_foam_hint() == " (OpenFOAM env not found)"
    assert runner._with_no_foam_hint("x") == "x (OpenFOAM env not found)"

    monkeypatch.setenv("WM_PROJECT_DIR", "/wm")
    assert runner.tool_status_mode() == "mode: limited (/wm)"

    hint_dir = tmp_path / "job-control"
    monkeypatch.setenv("FOAM_JOB_DIR", str(hint_dir))
    assert runner._job_dir_hint() is not None
    hint_dir.mkdir()
    assert runner._job_dir_hint() is None
    assert runner._maybe_job_hint("foamPrintJobs") is None
    assert runner._maybe_job_hint("blockMesh") is None


def test_runner_load_presets_parsing_and_read_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    cfg = case / "ofti.tools"
    cfg.write_text(
        "\n".join(
            [
                "# comment",
                "missing separator",
                "empty-name: ",
                "ok: echo 1",
                "bad: \"unterminated",
            ],
        ),
    )
    assert runner._load_presets_from_path(cfg) == [("ok", ["echo", "1"])]

    orig_read_text = Path.read_text

    def _boom(
        self: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        if self == cfg:
            raise OSError("nope")
        return orig_read_text(self, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", _boom)
    assert runner._load_presets_from_path(cfg) == []


def test_runner_show_message_raises_on_quit_key(monkeypatch: pytest.MonkeyPatch) -> None:
    screen = _Screen(keys=[ord("q")])
    monkeypatch.setattr(runner, "key_in", lambda key, _keys: key == ord("q"))
    monkeypatch.setattr(runner, "get_config", lambda: types.SimpleNamespace(keys={"quit": [ord("q")] }))
    with pytest.raises(QuitAppError):
        runner._show_message(screen, "bye")


def test_run_simple_tool_prefers_runfunctions_then_bashrc(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen()
    seen: list[str] = []

    monkeypatch.setenv("WM_PROJECT_DIR", "/wm")
    monkeypatch.setattr(runner, "get_config", lambda: types.SimpleNamespace(use_runfunctions=True))
    monkeypatch.setattr(runner, "_run_shell_tool", lambda *_a, **_k: seen.append(str(_a[3])))
    runner._run_simple_tool(screen, case, "blockMesh", ["blockMesh", "-latestTime"])
    assert "runApplication" in seen[-1]

    monkeypatch.setattr(runner, "get_config", lambda: types.SimpleNamespace(use_runfunctions=False))
    monkeypatch.setattr(runner, "resolve_openfoam_bashrc", lambda: "/etc/bashrc")
    runner._run_simple_tool(screen, case, "checkMesh", ["checkMesh"])
    assert seen[-1] == "checkMesh"


def test_run_simple_tool_direct_and_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen()
    shown: list[str] = []
    viewed: list[str] = []

    class _Viewer:
        def __init__(self, _stdscr: object, text: str) -> None:
            viewed.append(text)

        def display(self) -> None:
            return None

    monkeypatch.delenv("WM_PROJECT_DIR", raising=False)
    monkeypatch.setattr(runner, "resolve_openfoam_bashrc", lambda: None)
    monkeypatch.setattr(
        runner,
        "run_trusted",
        lambda *_a, **_k: types.SimpleNamespace(returncode=0, stdout="ok\n", stderr=""),
    )
    monkeypatch.setattr(runner, "Viewer", _Viewer)
    monkeypatch.setattr(runner, "_show_message", lambda _s, text: shown.append(text))
    runner._run_simple_tool(screen, case, "foamPrintJobs", ["foamPrintJobs"])
    assert viewed and "foamPrintJobs" in viewed[-1]

    monkeypatch.setattr(
        runner,
        "run_trusted",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("boom")),
    )
    runner._run_simple_tool(screen, case, "foamPrintJobs", ["foamPrintJobs"])
    assert "Failed to run foamPrintJobs" in shown[-1]


def test_run_shell_tool_and_capture_commands(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen()
    viewed: list[str] = []
    shown: list[str] = []
    captured: dict[str, object] = {}

    class _Viewer:
        def __init__(self, _stdscr: object, text: str) -> None:
            viewed.append(text)

        def display(self) -> None:
            return None

    monkeypatch.setenv("BASH_ENV", "x")
    monkeypatch.setenv("ENV", "y")
    monkeypatch.setattr(runner, "with_bashrc", lambda cmd: cmd)
    monkeypatch.setattr(runner, "_expand_shell_command", lambda cmd, _case: cmd)
    monkeypatch.setattr(runner, "Viewer", _Viewer)
    monkeypatch.setattr(runner, "_show_message", lambda _s, text: shown.append(text))

    def _ok(argv: list[str], **kwargs: object) -> object:
        captured["argv"] = argv
        captured.update(kwargs)
        return types.SimpleNamespace(returncode=0, stdout="done\n", stderr="")

    monkeypatch.setattr(runner, "run_trusted", _ok)
    runner._run_shell_tool(screen, case, "echo", "echo hi")
    assert captured["argv"] == ["bash", "--noprofile", "--norc", "-c", "echo hi"]
    env = captured["env"]
    assert isinstance(env, dict)
    assert "BASH_ENV" not in env and "ENV" not in env
    assert viewed

    monkeypatch.setattr(
        runner,
        "run_trusted",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("no shell")),
    )
    runner._run_shell_tool(screen, case, "echo", "echo hi")
    assert "Failed to run echo" in shown[-1]


def test_run_tool_command_variants(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen()
    viewed: list[str] = []
    status_lines: list[str] = []
    shown: list[str] = []

    class _Viewer:
        def __init__(self, _stdscr: object, text: str) -> None:
            viewed.append(text)

        def display(self) -> None:
            return None

    monkeypatch.setattr(runner, "Viewer", _Viewer)
    monkeypatch.setattr(runner, "status_message", lambda _s, text: status_lines.append(text))
    monkeypatch.setattr(runner, "_show_message", lambda _s, text: shown.append(text))
    monkeypatch.setattr(
        runner,
        "run_trusted",
        lambda *_a, **_k: types.SimpleNamespace(returncode=2, stdout="a\n", stderr="b\n"),
    )

    runner.run_tool_command(screen, case, "demo", ["echo", "1"], status="run")
    assert status_lines[-1] == "run"
    assert viewed
    assert (case / "log.demo").is_file()

    captured = runner.run_tool_command_capture(screen, case, "demo", ["echo", "1"], status=None)
    assert captured is not None and captured.returncode == 2

    monkeypatch.setattr(
        runner,
        "run_trusted",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("oops")),
    )
    assert runner.run_tool_command_capture(screen, case, "demo", ["echo", "1"]) is None
    assert "Failed to run demo" in shown[-1]


def test_write_tool_log_ignores_empty_and_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    runner._write_tool_log(case, "x", "", "")
    assert not (case / "log.x").exists()

    orig_write_text = Path.write_text

    def _raise_on_log_y(
        self: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        if self.name == "log.y":
            raise OSError("nope")
        return orig_write_text(self, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(Path, "write_text", _raise_on_log_y)
    runner._write_tool_log(case, "y", "out", "err")
    assert not (case / "log.y").exists()

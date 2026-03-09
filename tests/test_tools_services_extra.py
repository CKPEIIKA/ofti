from __future__ import annotations

import types
from pathlib import Path

import pytest

from ofti.core import tool_dicts_service
from ofti.tools import case_ops, reconstruct, shell_tools, yplus


class _Screen:
    def __init__(self, keys: list[int] | None = None) -> None:
        self._keys = list(keys or [ord("h")])
        self.lines: list[str] = []
        self.timeout_value = -1

    def clear(self) -> None:
        self.lines.clear()

    def addstr(self, *args: object) -> None:
        self.lines.append(str(args[-1]))

    def refresh(self) -> None:
        return None

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("h")

    def timeout(self, value: int) -> None:
        self.timeout_value = value

    def getmaxyx(self) -> tuple[int, int]:
        return (24, 100)

    def getyx(self) -> tuple[int, int]:
        return (0, 0)

    def attron(self, *_args: object) -> None:
        return None

    def attroff(self, *_args: object) -> None:
        return None

    def move(self, *_args: object) -> None:
        return None

    def clrtoeol(self) -> None:
        return None


class _Menu:
    def __init__(self, choice: int) -> None:
        self._choice = choice

    def navigate(self) -> int:
        return self._choice


def test_case_ops_open_paraview_and_clone_branches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen()
    shown: list[str] = []
    viewer_texts: list[str] = []
    runs: list[list[str]] = []

    monkeypatch.setattr(case_ops, "_show_message", lambda _s, text: shown.append(text))
    monkeypatch.setattr(case_ops.curses, "endwin", lambda: None)
    monkeypatch.setattr(case_ops.shutil, "which", lambda _name: "/usr/bin/paraview")
    monkeypatch.setattr(case_ops, "run_trusted", lambda cmd, **_k: runs.append(list(cmd)))
    case_ops.open_paraview_screen(screen, case)
    assert runs and runs[-1][0] == "/usr/bin/paraview"

    target_file = case / f"{case.name}.foam"
    orig_write_text = Path.write_text

    def _write_fail(
        self: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        if self == target_file:
            raise OSError("no write")
        return orig_write_text(self, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(Path, "write_text", _write_fail)
    case_ops.open_paraview_screen(screen, case)
    assert "Failed to create" in shown[-1]

    monkeypatch.setattr(case_ops, "prompt_line", lambda *_a, **_k: None)
    case_ops.clone_case(screen, case, name=None)
    monkeypatch.setattr(case_ops, "prompt_line", lambda *_a, **_k: "")
    case_ops.clone_case(screen, case, name=None)

    monkeypatch.setattr(case_ops, "copy_case_directory", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad")))
    case_ops.clone_case(screen, case, name="clone")
    assert shown[-1] == "bad"

    monkeypatch.setattr(case_ops, "copy_case_directory", lambda *_a, **_k: (_ for _ in ()).throw(OSError("io")))
    case_ops.clone_case(screen, case, name="clone")
    assert "Failed to clone case" in shown[-1]

    class _Viewer:
        def __init__(self, _s: object, text: str) -> None:
            viewer_texts.append(text)

        def display(self) -> None:
            return None

    monkeypatch.setattr(case_ops, "Viewer", _Viewer)
    monkeypatch.setattr(case_ops, "copy_case_directory", lambda *_a, **_k: case.parent / "copy")
    case_ops.clone_case(screen, case, name="copy")
    assert "Cloned case to" in viewer_texts[-1]


def test_tool_dicts_service_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    path = case / "system" / "fooDict"
    path.parent.mkdir(parents=True)

    path.write_text("existing\n")
    result = tool_dicts_service.ensure_dict(case, "foo", path, None, generate=True)
    assert result.created is True and result.source is None

    missing = case / "system" / "missingDict"
    result = tool_dicts_service.ensure_dict(case, "missing", missing, None, generate=False)
    assert result.created is False

    monkeypatch.setattr(tool_dicts_service, "_generate_with_helper", lambda *_a, **_k: False)
    stub_res = tool_dicts_service.ensure_dict(case, "bar", missing, ["helper"], generate=True)
    assert stub_res.created is True and stub_res.source == "stub"
    assert missing.is_file()

    monkeypatch.setattr(tool_dicts_service, "_generate_with_helper", lambda *_a, **_k: True)
    example = case / "system" / "exampleDict"
    ok_res = tool_dicts_service.ensure_dict(case, "example", example, ["helper"], generate=True)
    assert ok_res.created is True and ok_res.source == "example"

    monkeypatch.setattr(tool_dicts_service.foamlib_integration, "available", lambda: False)
    assert tool_dicts_service.apply_assignment(case, Path("system/controlDict"), ["a"], "1") is False

    monkeypatch.setattr(tool_dicts_service.foamlib_integration, "available", lambda: True)
    monkeypatch.setattr(tool_dicts_service.foamlib_integration, "is_foam_file", lambda _path: True)
    assert tool_dicts_service.apply_assignment(case, Path("system/nope"), ["a"], "1") is False

    target = case / "system" / "controlDict"
    target.write_text("application simpleFoam;\n")
    monkeypatch.setattr(tool_dicts_service.foamlib_integration, "apply_assignment", lambda *_a, **_k: True)
    assert tool_dicts_service.apply_assignment(case, Path("system/controlDict"), ["application"], "icoFoam") is True

    monkeypatch.setattr(tool_dicts_service, "apply_assignment", lambda *_a, **_k: False)
    monkeypatch.setattr(tool_dicts_service.entry_io, "write_entry", lambda *_a, **_k: True)
    assert tool_dicts_service.apply_assignment_or_write(case, target, ["k"], "v") is True


def test_tool_dicts_service_generate_with_helper_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    out = case / "system" / "sampleDict"
    out.parent.mkdir(parents=True)

    assert tool_dicts_service._generate_with_helper(case, None, out) is False

    monkeypatch.setattr(tool_dicts_service, "write_example_template", lambda *_a, **_k: True)
    assert tool_dicts_service._generate_with_helper(case, ["helper"], out) is True

    monkeypatch.setattr(tool_dicts_service, "write_example_template", lambda *_a, **_k: False)
    monkeypatch.setattr(
        tool_dicts_service,
        "run_trusted",
        lambda *_a, **_k: types.SimpleNamespace(returncode=0, stdout="FoamFile\n{}\n", stderr=""),
    )
    assert tool_dicts_service._generate_with_helper(case, ["helper"], out) is True
    assert "FoamFile" in out.read_text()

    monkeypatch.setattr(
        tool_dicts_service,
        "run_trusted",
        lambda *_a, **_k: types.SimpleNamespace(returncode=1, stdout="", stderr="bad"),
    )
    assert tool_dicts_service._generate_with_helper(case, ["helper"], out) is False

    monkeypatch.setattr(
        tool_dicts_service,
        "run_trusted",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("boom")),
    )
    assert tool_dicts_service._generate_with_helper(case, ["helper"], out) is False


def test_yplus_screen_and_capture_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen(keys=[ord("r")])
    shown: list[str] = []
    viewed: list[str] = []
    original_capture = yplus._run_tool_capture

    monkeypatch.setattr(yplus, "_show_message", lambda _s, text: shown.append(text))
    monkeypatch.setattr(yplus, "_write_tool_log", lambda *_a, **_k: None)
    monkeypatch.setattr(yplus, "_run_tool_capture", lambda *_a, **_k: ("", ""))
    yplus.yplus_screen(screen, case)
    assert "No yPlus stats found" in shown[-1]

    class _Viewer:
        def __init__(self, _s: object, text: str) -> None:
            viewed.append(text)

        def display(self) -> None:
            return None

    monkeypatch.setattr(yplus, "Viewer", _Viewer)
    monkeypatch.setattr(yplus, "_run_tool_capture", lambda *_a, **_k: ("yPlus: min 1 max 2 avg 1.5", ""))
    yplus.yplus_screen(screen, case)
    assert viewed and "yPlus raw output" in viewed[-1]

    monkeypatch.setattr(yplus, "_run_tool_capture", original_capture)
    monkeypatch.setenv("WM_PROJECT_DIR", "/wm")
    monkeypatch.setattr(yplus, "get_config", lambda: types.SimpleNamespace(use_runfunctions=True))
    monkeypatch.setattr(yplus, "_run_shell_capture", lambda *_a, **_k: ("ok", ""))
    assert yplus._run_tool_capture(case, "yPlus")[0] == "ok"

    monkeypatch.setattr(yplus, "get_config", lambda: types.SimpleNamespace(use_runfunctions=False))
    monkeypatch.setattr(yplus, "resolve_openfoam_bashrc", lambda: "/etc/bashrc")
    assert yplus._run_tool_capture(case, "yPlus")[0] == "ok"

    monkeypatch.setattr(yplus, "resolve_openfoam_bashrc", lambda: None)
    monkeypatch.setattr(yplus, "run_trusted", lambda *_a, **_k: types.SimpleNamespace(stdout="A", stderr="B"))
    assert yplus._run_tool_capture(case, "yPlus") == ("A", "B")

    monkeypatch.setattr(yplus, "run_trusted", lambda *_a, **_k: (_ for _ in ()).throw(OSError("x")))
    _out, err = yplus._run_tool_capture(case, "yPlus")
    assert "Failed to run yPlus" in err


def test_shell_and_reconstruct_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen(keys=[ord("h"), ord("q")])
    shown: list[str] = []
    viewed: list[str] = []

    monkeypatch.setattr(shell_tools, "_show_message", lambda _s, text: shown.append(text))
    shell_tools.run_shell_script_screen(screen, case)
    assert "No *.sh scripts found" in shown[-1]

    script = case / "run.sh"
    script.write_text("echo ok\n")
    monkeypatch.setattr(shell_tools, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(
        shell_tools,
        "run_trusted",
        lambda *_a, **_k: types.SimpleNamespace(returncode=0, stdout="ok\n", stderr=""),
    )

    class _Viewer:
        def __init__(self, _s: object, text: str) -> None:
            viewed.append(text)

        def display(self) -> None:
            return None

    monkeypatch.setattr(shell_tools, "Viewer", _Viewer)
    shell_tools.run_shell_script_screen(screen, case)
    assert viewed and "sh run.sh" in viewed[-1]

    monkeypatch.setattr(
        shell_tools,
        "run_trusted",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("boom")),
    )
    shell_tools.run_shell_script_screen(screen, case)
    assert "Failed to run run.sh" in shown[-1]

    monkeypatch.setattr(shell_tools, "get_last_tool_run", lambda: None)
    shell_tools.rerun_last_tool(screen, case)
    assert "No previous tool run recorded." in shown[-1]

    monkeypatch.setattr(
        shell_tools,
        "get_last_tool_run",
        lambda: types.SimpleNamespace(name="demo", kind="shell", command="echo 1"),
    )
    called_shell: list[str] = []
    monkeypatch.setattr(shell_tools, "_run_shell_tool", lambda *_a, **_k: called_shell.append(str(_a[3])))
    shell_tools.rerun_last_tool(screen, case)
    assert called_shell[-1] == "echo 1"

    monkeypatch.setattr(
        shell_tools,
        "get_last_tool_run",
        lambda: types.SimpleNamespace(name="demo", kind="simple", command=["echo", "1"]),
    )
    called_simple: list[list[str]] = []
    monkeypatch.setattr(shell_tools, "_run_simple_tool", lambda *_a, **_k: called_simple.append(list(_a[3])))
    shell_tools.rerun_last_tool(screen, case)
    assert called_simple[-1] == ["echo", "1"]

    monkeypatch.setattr(reconstruct, "_show_message", lambda _s, text: shown.append(text))
    reconstruct.reconstruct_manager_screen(screen, case)
    assert "Case is not decomposed" in shown[-1]

    (case / "processor0").mkdir()
    monkeypatch.setattr(reconstruct, "build_menu", lambda *_a, **_k: _Menu(1))
    rec_calls: list[list[str]] = []
    monkeypatch.setattr(reconstruct, "_run_simple_tool", lambda *_a, **_k: rec_calls.append(list(_a[3])))
    reconstruct.reconstruct_manager_screen(screen, case)
    assert rec_calls[-1] == ["reconstructPar", "-latestTime"]

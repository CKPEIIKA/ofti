from __future__ import annotations

import types
from pathlib import Path

import pytest

from ofti.tools import input_prompts, job_control, logs_select, mesh_utils, pipeline


class _Screen:
    def __init__(self, keys: list[int] | None = None, height: int = 24, width: int = 90) -> None:
        self._keys = list(keys or [])
        self.height = height
        self.width = width
        self.lines: list[str] = []

    def clear(self) -> None:
        self.lines.clear()

    def erase(self) -> None:
        self.lines.clear()

    def getmaxyx(self) -> tuple[int, int]:
        return (self.height, self.width)

    def addstr(self, *args: object) -> None:
        self.lines.append(str(args[-1]))

    def refresh(self) -> None:
        return None

    def move(self, *_args: object) -> None:
        return None

    def clrtoeol(self) -> None:
        return None

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("h")

    def attron(self, *_args: object) -> None:
        return None

    def attroff(self, *_args: object) -> None:
        return None


class _Menu:
    def __init__(self, choice: int) -> None:
        self._choice = choice

    def navigate(self) -> int:
        return self._choice


def test_input_prompt_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(input_prompts, "prompt_input", lambda *_a, **_k: "  abc  ")
    assert input_prompts.prompt_line(_Screen(), "x") == "abc"

    monkeypatch.setattr(input_prompts, "prompt_input", lambda *_a, **_k: "")
    assert input_prompts.prompt_args_line(_Screen(), "x") == []

    messages: list[str] = []
    monkeypatch.setattr(input_prompts, "_show_message", lambda _s, text: messages.append(text))
    monkeypatch.setattr(input_prompts, "prompt_input", lambda *_a, **_k: '"')
    assert input_prompts.prompt_args_line(_Screen(), "x") is None
    assert "Invalid arguments" in messages[-1]
    assert input_prompts.prompt_command_line(_Screen(), "x") is None


def test_logs_select_helpers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert logs_select._tail_text("a\nb\nc", max_lines=2).startswith("... (1 lines omitted)")
    assert logs_select._tail_text("", max_lines=2) == "(empty)"

    case = tmp_path / "case"
    case.mkdir()
    log_solver = case / "log.simpleFoam"
    log_other = case / "log.other"
    log_solver.write_text("solver\n")
    log_other.write_text("other\n")
    monkeypatch.setattr(logs_select, "detect_solver", lambda _case: "simpleFoam")
    assert logs_select._preferred_log_file(case) == log_solver

    messages: list[str] = []
    monkeypatch.setattr(logs_select, "_show_message", lambda _s, text: messages.append(text))
    empty = tmp_path / "empty"
    empty.mkdir()
    assert logs_select._select_log_file(empty, _Screen()) is None
    assert "No log.* files found" in messages[-1]

    monkeypatch.setattr(logs_select, "build_menu", lambda *_a, **_k: _Menu(0))
    selected = logs_select._select_log_file(case, _Screen())
    assert selected is not None and selected.name.startswith("log.")

    monkeypatch.setattr(logs_select, "detect_solver", lambda _case: "unknown")
    assert logs_select._select_solver_log_file(case, _Screen(), title="x") is None


def test_mesh_utils_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    screen = _Screen()
    case = tmp_path / "case"
    case.mkdir()
    called: list[list[str]] = []
    monkeypatch.setattr(mesh_utils, "run_tool_command", lambda *_a, **_k: called.append(list(_a[3])))
    mesh_utils.renumber_mesh_screen(screen, case)
    assert called[-1] == ["renumberMesh"]

    monkeypatch.setattr(mesh_utils, "build_menu", lambda *_a, **_k: _Menu(3))
    monkeypatch.setattr(mesh_utils, "prompt_args_line", lambda *_a, **_k: ["-rotate", "(1 0 0)"])
    mesh_utils.transform_points_screen(screen, case)
    assert called[-1] == ["transformPoints", "-rotate", "(1 0 0)"]

    monkeypatch.setattr(mesh_utils, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(mesh_utils, "prompt_line", lambda *_a, **_k: "(1 0 0)")
    mesh_utils.transform_points_screen(screen, case)
    assert called[-1] == ["transformPoints", "-translate", "(1 0 0)"]

    messages: list[str] = []
    monkeypatch.setattr(mesh_utils, "_show_message", lambda _s, text: messages.append(text))
    mesh_utils.cfmesh_screen(screen, case)
    assert "system/cfMeshDict not found." in messages[-1]

    (case / "system").mkdir()
    (case / "system" / "cfMeshDict").write_text("ok\n")
    monkeypatch.setattr(mesh_utils, "build_menu", lambda *_a, **_k: _Menu(1))
    mesh_utils.cfmesh_screen(screen, case)
    assert "log.cartesianMesh not found." in messages[-1]


def test_pipeline_pick_tool_and_runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen()

    monkeypatch.setattr(
        pipeline,
        "_pipeline_tool_catalog",
        lambda _case: [("[config] set entry", [pipeline.PIPELINE_SET_COMMAND])],
    )
    monkeypatch.setattr(pipeline, "build_menu", lambda *_a, **_k: _Menu(0))
    prompts = iter(["system/controlDict", "application", "simpleFoam"])
    monkeypatch.setattr(pipeline, "prompt_line", lambda *_a, **_k: next(prompts))
    assert pipeline._pipeline_pick_tool(screen, case) == [
        pipeline.PIPELINE_SET_COMMAND,
        "system/controlDict",
        "application",
        "simpleFoam",
    ]

    monkeypatch.setattr(
        pipeline,
        "_pipeline_tool_catalog",
        lambda _case: [("[custom] echo", ["echo"]), ("[custom] command", [])],
    )
    monkeypatch.setattr(pipeline, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(pipeline, "prompt_line", lambda *_a, **_k: "hello")
    assert pipeline._pipeline_pick_tool(screen, case) == ["echo", "hello"]
    monkeypatch.setattr(pipeline, "build_menu", lambda *_a, **_k: _Menu(1))
    monkeypatch.setattr(pipeline, "prompt_command_line", lambda *_a, **_k: ["echo", "cmd"])
    assert pipeline._pipeline_pick_tool(screen, case) == ["echo", "cmd"]

    monkeypatch.setattr(
        pipeline.pipeline_service,
        "run_pipeline_commands",
        lambda *_a, **_k: ["step1", "step2"],
    )
    shown: list[str] = []

    class _Viewer:
        def __init__(self, _s: object, text: str) -> None:
            shown.append(text)

        def display(self) -> None:
            return None

    monkeypatch.setattr(pipeline, "Viewer", _Viewer)
    pipeline._run_pipeline_commands(screen, case, [["echo", "x"]])
    assert "step1" in shown[-1]


def test_pipeline_editor_and_runner_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    path = case / pipeline.PIPELINE_FILENAME
    screen = _Screen(keys=[ord("x")])
    messages: list[str] = []
    monkeypatch.setattr(pipeline, "_show_message", lambda _s, text: messages.append(text))

    pipeline.pipeline_runner_screen(screen, case)
    assert f"{pipeline.PIPELINE_FILENAME} not found" in messages[-1]

    path.write_text("#!/bin/bash\n")
    monkeypatch.setattr(
        pipeline.pipeline_service,
        "read_pipeline_commands",
        lambda _path: ([], ["Missing header"]),
    )
    shown: list[str] = []

    class _Viewer:
        def __init__(self, _s: object, text: str) -> None:
            shown.append(text)

        def display(self) -> None:
            return None

    monkeypatch.setattr(pipeline, "Viewer", _Viewer)
    pipeline.pipeline_runner_screen(screen, case)
    assert "PIPELINE PARSE ERRORS" in shown[-1]

    # Editor: create missing file and exit immediately.
    missing_case = tmp_path / "missing-case"
    missing_case.mkdir()
    writes: list[tuple[Path, list[list[str]]]] = []
    monkeypatch.setattr(
        pipeline.pipeline_service,
        "write_pipeline_file",
        lambda p, commands: writes.append((p, commands)),
    )
    pipeline.pipeline_editor_screen(_Screen(keys=[ord("c"), ord("h")]), missing_case)
    assert writes

    # Editor with commands: add and run then exit.
    monkeypatch.setattr(
        pipeline.pipeline_service,
        "read_pipeline_commands",
        lambda _path: ([["echo", "1"]], []),
    )
    monkeypatch.setattr(pipeline, "_render_pipeline_editor", lambda *_a, **_k: None)
    monkeypatch.setattr(pipeline, "_pipeline_pick_tool", lambda *_a, **_k: ["echo", "2"])
    monkeypatch.setattr(pipeline, "_run_pipeline_commands", lambda *_a, **_k: None)
    pipeline.pipeline_editor_screen(_Screen(keys=[ord("a"), ord("r"), ord("h")]), case)


def test_job_control_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen()
    messages: list[str] = []
    monkeypatch.setattr(job_control, "_show_message", lambda _s, text: messages.append(text))

    monkeypatch.setattr(job_control.watch_service, "refresh_jobs", lambda _case: [])
    job_control.stop_job_screen(screen, case)
    assert "No running jobs to stop." in messages[-1]

    monkeypatch.setattr(
        job_control.watch_service,
        "refresh_jobs",
        lambda _case: [{"id": "1", "name": "solver", "pid": "bad", "status": "running"}],
    )
    monkeypatch.setattr(job_control, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(
        job_control.watch_service,
        "stop_payload",
        lambda *_a, **_k: {"failed": [{"pid": "bad", "error": "invalid pid"}], "stopped": []},
    )
    job_control.stop_job_screen(screen, case)
    assert "invalid pid" in messages[-1]

    monkeypatch.setattr(
        job_control.watch_service,
        "refresh_jobs",
        lambda _case: [{"id": "1", "name": "solver", "pid": 42, "status": "running"}],
    )
    monkeypatch.setattr(
        job_control.watch_service,
        "stop_payload",
        lambda *_a, **_k: {"failed": [], "stopped": [{"pid": 42}]},
    )
    job_control.stop_job_screen(screen, case)
    assert "Sent SIGTERM to pid 42." in messages[-1]

    # Start background command (direct path without bashrc/runfunctions).
    started: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        job_control.run_ops,
        "expand_command",
        lambda _case, cmd: list(cmd),
    )
    monkeypatch.setattr(
        job_control.run_ops,
        "execute_case_command",
        lambda _case, name, cmd, **_kwargs: (
            started.append((str(name), list(cmd)))
            or types.SimpleNamespace(pid=77)
        ),
    )
    job_control._start_background_command(screen, case, "blockMesh", ["blockMesh"])
    assert started[-1] == ("blockMesh", ["blockMesh"])

    # Shared path is also used for other tools.
    job_control._start_background_command(screen, case, "checkMesh", ["checkMesh"])
    assert started[-1] == ("checkMesh", ["checkMesh"])

    assert job_control._log_path(case, "name with !").name == "log.namewith"


def test_run_tool_background_screen_custom(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen()
    monkeypatch.setattr(
        job_control,
        "_background_tool_catalog",
        lambda _case: [("[custom] command", [])],
    )
    monkeypatch.setattr(job_control, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(job_control, "prompt_command_line", lambda *_a, **_k: ["echo", "hello"])
    called: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        job_control,
        "_start_background_command",
        lambda _s, _c, name, cmd: called.append((name, cmd)),
    )
    job_control.run_tool_background_screen(screen, case)
    assert called == [("echo", ["echo", "hello"])]

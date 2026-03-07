from __future__ import annotations

import curses
from pathlib import Path

import pytest

from ofti.tools import pipeline


class _Screen:
    def __init__(self, keys: list[int] | None = None, *, height: int = 24, width: int = 100) -> None:
        self._keys = list(keys or [])
        self.height = height
        self.width = width
        self.lines: list[str] = []

    def clear(self) -> None:
        self.lines.clear()

    def addstr(self, *args: object) -> None:
        self.lines.append(str(args[-1]))

    def refresh(self) -> None:
        return None

    def getmaxyx(self) -> tuple[int, int]:
        return (self.height, self.width)

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


def _capture_viewer(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    shown: list[str] = []

    class _Viewer:
        def __init__(self, _screen: object, text: str) -> None:
            shown.append(text)

        def display(self) -> None:
            return None

    monkeypatch.setattr(pipeline, "Viewer", _Viewer)
    return shown


def test_pipeline_runner_screen_no_commands(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    path = case / pipeline.PIPELINE_FILENAME
    path.write_text(f"{pipeline.PIPELINE_HEADER}\n")
    messages: list[str] = []
    monkeypatch.setattr(pipeline, "_show_message", lambda _s, text: messages.append(text))
    monkeypatch.setattr(pipeline.pipeline_service, "read_pipeline_commands", lambda _path: ([], []))

    pipeline.pipeline_runner_screen(_Screen(), case)
    assert messages[-1] == f"No commands found in {pipeline.PIPELINE_FILENAME}."


def test_pipeline_editor_missing_file_and_parse_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    missing_case = tmp_path / "missing-case"
    missing_case.mkdir()
    writes: list[tuple[Path, list[list[str]]]] = []
    monkeypatch.setattr(
        pipeline.pipeline_service,
        "write_pipeline_file",
        lambda p, commands: writes.append((p, commands)),
    )
    pipeline.pipeline_editor_screen(_Screen(keys=[ord("x")]), missing_case)
    assert writes == []

    case = tmp_path / "case"
    case.mkdir()
    path = case / pipeline.PIPELINE_FILENAME
    path.write_text("#!/bin/bash\n")
    monkeypatch.setattr(
        pipeline.pipeline_service,
        "read_pipeline_commands",
        lambda _path: ([], ["Missing header"]),
    )
    monkeypatch.setattr(pipeline, "_render_pipeline_editor", lambda *_a, **_k: None)
    pipeline.pipeline_editor_screen(_Screen(keys=[ord("c"), ord("h")]), case)
    assert writes and writes[-1][0] == path

    shown = _capture_viewer(monkeypatch)
    monkeypatch.setattr(
        pipeline.pipeline_service,
        "read_pipeline_commands",
        lambda _path: ([], ["unexpected token"]),
    )
    pipeline.pipeline_editor_screen(_Screen(), case)
    assert "PIPELINE PARSE ERRORS" in shown[-1]


def test_pipeline_editor_keypaths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    (case / pipeline.PIPELINE_FILENAME).write_text(f"{pipeline.PIPELINE_HEADER}\n")
    writes: list[list[list[str]]] = []
    monkeypatch.setattr(
        pipeline.pipeline_service,
        "write_pipeline_file",
        lambda _path, commands: writes.append([list(row) for row in commands]),
    )
    monkeypatch.setattr(pipeline, "_render_pipeline_editor", lambda *_a, **_k: None)

    monkeypatch.setattr(
        pipeline.pipeline_service,
        "read_pipeline_commands",
        lambda _path: ([["echo", "1"]], []),
    )
    messages: list[str] = []
    monkeypatch.setattr(pipeline, "_show_message", lambda _s, text: messages.append(text))
    monkeypatch.setattr(pipeline, "prompt_line", lambda *_a, **_k: '"')
    pipeline.pipeline_editor_screen(_Screen(keys=[ord("e"), ord("h")]), case)
    assert messages[-1] == "Invalid command line."

    monkeypatch.setattr(pipeline, "prompt_line", lambda *_a, **_k: "")
    pipeline.pipeline_editor_screen(_Screen(keys=[ord("e"), ord("h")]), case)

    monkeypatch.setattr(pipeline, "prompt_line", lambda *_a, **_k: "echo 2")
    pipeline.pipeline_editor_screen(_Screen(keys=[ord("e"), ord("h")]), case)
    assert any(row == ["echo", "2"] for rows in writes for row in rows)

    monkeypatch.setattr(
        pipeline.pipeline_service,
        "read_pipeline_commands",
        lambda _path: ([["echo", "1"], ["echo", "2"]], []),
    )
    monkeypatch.setattr(pipeline, "_run_pipeline_commands", lambda *_a, **_k: messages.append("run"))
    pipeline.pipeline_editor_screen(_Screen(keys=[ord("j"), ord("k"), ord("u"), ord("n"), ord("d"), ord("r"), ord("h")]), case)
    assert "run" in messages

    monkeypatch.setattr(
        pipeline.pipeline_service,
        "read_pipeline_commands",
        lambda _path: ([], []),
    )
    pipeline.pipeline_editor_screen(_Screen(keys=[ord("r"), ord("h")]), case)
    assert messages[-1] == "Pipeline has no steps."


def test_pipeline_pick_tool_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen()

    monkeypatch.setattr(pipeline, "_pipeline_tool_catalog", lambda _case: [("tool", ["checkMesh"])])
    monkeypatch.setattr(pipeline, "build_menu", lambda *_a, **_k: _Menu(1))
    assert pipeline._pipeline_pick_tool(screen, case) is None

    monkeypatch.setattr(
        pipeline,
        "_pipeline_tool_catalog",
        lambda _case: [("[config] set entry", [pipeline.PIPELINE_SET_COMMAND])],
    )
    monkeypatch.setattr(pipeline, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(pipeline, "prompt_line", lambda *_a, **_k: " ")
    assert pipeline._pipeline_pick_tool(screen, case) is None

    prompts = iter(["system/controlDict", " ", "unused"])
    monkeypatch.setattr(pipeline, "prompt_line", lambda *_a, **_k: next(prompts))
    assert pipeline._pipeline_pick_tool(screen, case) is None

    prompts = iter(["system/controlDict", "application", None])
    monkeypatch.setattr(pipeline, "prompt_line", lambda *_a, **_k: next(prompts))
    assert pipeline._pipeline_pick_tool(screen, case) is None

    monkeypatch.setattr(pipeline, "_pipeline_tool_catalog", lambda _case: [("[custom] echo", ["echo"])])
    monkeypatch.setattr(pipeline, "prompt_line", lambda *_a, **_k: None)
    assert pipeline._pipeline_pick_tool(screen, case) is None

    monkeypatch.setattr(pipeline, "_pipeline_tool_catalog", lambda _case: [("[custom] command", [])])
    monkeypatch.setattr(pipeline, "prompt_command_line", lambda *_a, **_k: None)
    assert pipeline._pipeline_pick_tool(screen, case) is None

    monkeypatch.setattr(pipeline, "_pipeline_tool_catalog", lambda _case: [("plain", ["checkMesh"])])
    monkeypatch.setattr(pipeline, "prompt_args_line", lambda *_a, **_k: None)
    assert pipeline._pipeline_pick_tool(screen, case) == ["checkMesh"]

    monkeypatch.setattr(pipeline, "prompt_args_line", lambda *_a, **_k: ["-latestTime"])
    assert pipeline._pipeline_pick_tool(screen, case) == ["checkMesh", "-latestTime"]


def test_render_pipeline_editor_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline.curses, "color_pair", lambda _n: 1)
    screen = _Screen(height=6, width=40)
    pipeline._render_pipeline_editor(screen, [["echo", "1"], ["echo", "2"], ["echo", "3"]], cursor=2)
    assert any(">>" in line for line in screen.lines)

    class _ErrorScreen(_Screen):
        def addstr(self, *_args: object) -> None:
            raise curses.error()

    pipeline._render_pipeline_editor(_ErrorScreen(), [["echo", "1"]], cursor=0)

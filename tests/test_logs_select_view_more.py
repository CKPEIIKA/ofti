from __future__ import annotations

import curses
import os
import types
from pathlib import Path

import pytest

from ofti.app.tool_screens import logs_select, logs_view
from tests.testscreen import TestScreen as _Screen


class _Menu:
    def __init__(self, choice: int) -> None:
        self._choice = choice

    def navigate(self) -> int:
        return self._choice


def test_logs_select_fallback_and_solver_menu(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    old_log = case / "log.old"
    new_log = case / "log.new"
    old_log.write_text("old\n")
    new_log.write_text("new\n")
    monkeypatch.setattr(logs_select, "detect_solver", lambda _case: "unknown")
    assert logs_select._preferred_log_file(case) == new_log
    empty_case = tmp_path / "empty"
    empty_case.mkdir()
    assert logs_select._preferred_log_file(empty_case) is None

    monkeypatch.setattr(logs_select, "build_menu", lambda *_a, **_k: _Menu(2))
    assert logs_select._select_log_file(case, _Screen()) is None

    monkeypatch.setattr(logs_select, "detect_solver", lambda _case: "simpleFoam")
    solver_log = case / "log.simpleFoam"
    solver_log.write_text("solver\n")
    monkeypatch.setattr(logs_select, "build_menu", lambda *_a, **_k: _Menu(1))
    assert logs_select._select_solver_log_file(case, _Screen(), title="solver") is None
    monkeypatch.setattr(logs_select, "build_menu", lambda *_a, **_k: _Menu(0))
    assert logs_select._select_solver_log_file(case, _Screen(), title="solver") == solver_log


def test_select_solver_log_file_missing_solver_logs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    messages: list[str] = []
    monkeypatch.setattr(logs_select, "_show_message", lambda _s, text: messages.append(text))
    monkeypatch.setattr(logs_select, "detect_solver", lambda _case: "simpleFoam")
    assert logs_select._select_solver_log_file(case, _Screen(), title="solver") is None
    assert messages[-1] == "No log.simpleFoam* files found in case directory."


def test_logs_screen_handles_none_error_and_tail_dispatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    messages: list[str] = []
    monkeypatch.setattr(logs_view, "_show_message", lambda _s, text: messages.append(text))

    tail_calls: list[Path] = []
    monkeypatch.setattr(logs_view, "log_tail_screen", lambda _s, path: tail_calls.append(path))
    choices = iter([0, 0, 1, 3])
    monkeypatch.setattr(logs_view, "build_menu", lambda *_a, **_k: _Menu(next(choices)))

    missing = case / "log.missing"
    selected = iter([None, missing])
    monkeypatch.setattr(logs_view, "_select_log_file", lambda *_a, **_k: next(selected))
    logs_view.logs_screen(_Screen(), case)
    assert tail_calls == [case]
    assert "Failed to read log.missing" in messages[-1]


def test_logs_screen_large_log_uses_bounded_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    log_path = case / "log.big"
    log_path.write_text("tail-data\n")
    seen: dict[str, object] = {}

    choices = iter([0, 3])
    monkeypatch.setattr(logs_view, "build_menu", lambda *_a, **_k: _Menu(next(choices)))
    monkeypatch.setattr(logs_view, "_select_log_file", lambda *_a, **_k: log_path)
    orig_stat = os.stat

    def _stat(path: str | bytes | os.PathLike[str] | os.PathLike[bytes], *args: object, **kwargs: object) -> os.stat_result:
        result = orig_stat(path, *args, **kwargs)
        if Path(path) == log_path:
            return os.stat_result(
                (
                    result.st_mode,
                    result.st_ino,
                    result.st_dev,
                    result.st_nlink,
                    result.st_uid,
                    result.st_gid,
                    logs_view._LOG_VIEW_MAX_BYTES + 1,
                    result.st_atime,
                    result.st_mtime,
                    result.st_ctime,
                ),
            )
        return result

    monkeypatch.setattr(os, "stat", _stat)
    monkeypatch.setattr(
        logs_view,
        "read_log_text",
        lambda path, *, max_bytes: seen.update({"path": path, "max_bytes": max_bytes}) or "tail-data\n",
    )
    shown: list[str] = []
    monkeypatch.setattr(logs_view.Viewer, "display", lambda self: shown.append(self.content))
    logs_view.logs_screen(_Screen(), case)
    assert seen["path"] == log_path
    assert seen["max_bytes"] == logs_view._LOG_VIEW_MAX_BYTES
    assert "large log: showing last" in shown[-1]
    assert "tail-data" in shown[-1]


def test_log_tail_screen_branches_and_alerts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    messages: list[str] = []
    monkeypatch.setattr(logs_view, "_show_message", lambda _s, text: messages.append(text))
    monkeypatch.setattr(logs_view, "get_config", lambda: types.SimpleNamespace(courant_limit=0.5, keys={"back": [ord("h")]}))
    monkeypatch.setattr(logs_view, "key_in", lambda key, keys: key in keys)

    logs_view.log_tail_screen(_Screen(), case)
    assert messages[-1] == "No log.* files found in case directory."

    log_path = case / "log.simpleFoam"
    log_path.write_text("line\n")
    monkeypatch.setattr(logs_view, "build_menu", lambda *_a, **_k: _Menu(1))
    logs_view.log_tail_screen(_Screen(), case)

    monkeypatch.setattr(logs_view, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(
        logs_view,
        "read_log_tail_lines",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("io bad")),
    )
    logs_view.log_tail_screen(_Screen(), case)
    assert "Failed to read log.simpleFoam: io bad" in messages[-1]

    monkeypatch.undo()
    monkeypatch.setattr(logs_view, "get_config", lambda: types.SimpleNamespace(courant_limit=0.5, keys={"back": [ord("h")]}))
    monkeypatch.setattr(logs_view, "key_in", lambda key, keys: key in keys)
    monkeypatch.setattr(logs_view, "build_menu", lambda *_a, **_k: _Menu(0))
    log_path.write_text(
        "\n".join(
            [
                "Courant Number mean: 0.1 max: 1.2",
                "floating point exception",
                "nan detected",
                "FATAL ERROR",
            ],
        ),
    )

    class _TailScreen(_Screen):
        def __init__(self) -> None:
            super().__init__(keys=[ord("h")], height=20, width=120)

        def getyx(self) -> tuple[int, int]:
            return (len(self.lines), 0)

    logs_view.log_tail_screen(_TailScreen(), case)

    class _ErrorTailScreen(_TailScreen):
        def addstr(self, *args: object, **_kwargs: object) -> None:
            text = str(args[-1])
            if text.startswith("!! "):
                raise curses.error()
            super().addstr(*args)

    logs_view.log_tail_screen(_ErrorTailScreen(), case)


def test_log_tail_screen_uses_bounded_reads_and_resets_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    log_path = case / "log.simpleFoam"
    log_path.write_text("Time = 1\n")
    seen: dict[str, object] = {}

    class _BoundedScreen(_Screen):
        def __init__(self) -> None:
            super().__init__(keys=[ord("h")], height=12, width=80)
            self.timeout_values: list[int] = []

        def timeout(self, value: int) -> None:
            self.timeout_values.append(value)
            super().timeout(value)

        def getyx(self) -> tuple[int, int]:
            return (len(self.lines), 0)

    def _tail(path: Path, *, max_lines: int, max_bytes: int) -> list[str]:
        seen["path"] = path
        seen["max_lines"] = max_lines
        seen["max_bytes"] = max_bytes
        return ["Time = 1"]

    monkeypatch.setattr(logs_view, "get_config", lambda: types.SimpleNamespace(courant_limit=0.5, keys={"back": [ord("h")]}))
    monkeypatch.setattr(logs_view, "key_in", lambda key, keys: key in keys)
    monkeypatch.setattr(logs_view, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(logs_view, "read_log_tail_lines", _tail)
    screen = _BoundedScreen()
    logs_view.log_tail_screen(screen, case)
    assert seen["path"] == log_path
    assert seen["max_lines"] == logs_view._LOG_TAIL_MAX_LINES
    assert seen["max_bytes"] == logs_view._LOG_TAIL_MAX_BYTES
    assert screen.timeout_values[0] == logs_view._LOG_TAIL_POLL_MS
    assert screen.timeout_values[-1] == -1

from __future__ import annotations

from pathlib import Path

import pytest

from ofti.tools import cli_tools_screens as screens
from ofti.tools.cli_tools.run import RunResult


class _Menu:
    def __init__(self, choice: int) -> None:
        self._choice = choice

    def navigate(self) -> int:
        return self._choice


class _DummyScreen:
    pass


def _capture_viewer(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    shown: list[str] = []

    class _Viewer:
        def __init__(self, _stdscr: object, text: str) -> None:
            shown.append(text)

        def display(self) -> None:
            return None

    monkeypatch.setattr(screens, "Viewer", _Viewer)
    return shown


def test_cli_tools_screen_dispatches_sections(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    choices = iter([0, 1, 2, 3, 4])
    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(next(choices)))
    called: list[str] = []
    monkeypatch.setattr(screens, "_knife_screen", lambda *_a, **_k: called.append("knife"))
    monkeypatch.setattr(screens, "_plot_screen", lambda *_a, **_k: called.append("plot"))
    monkeypatch.setattr(screens, "_watch_screen", lambda *_a, **_k: called.append("watch"))
    monkeypatch.setattr(screens, "_run_screen", lambda *_a, **_k: called.append("run"))

    screens.cli_tools_screen(_DummyScreen(), tmp_path)
    assert called == ["knife", "plot", "watch", "run"]


def test_knife_screen_preflight_and_compare(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    shown = _capture_viewer(monkeypatch)
    case = tmp_path / "case"
    case.mkdir()

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(
        screens.knife_ops,
        "preflight_payload",
        lambda _case: {
            "case": str(case),
            "checks": {"system/controlDict": True},
            "solver_error": None,
            "ok": True,
        },
    )
    screens._knife_screen(_DummyScreen(), case)
    assert shown and "ok=True" in shown[-1]

    shown.clear()
    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(3))
    monkeypatch.setattr(screens, "prompt_line", lambda *_a, **_k: str(tmp_path / "other"))
    monkeypatch.setattr(
        screens.knife_ops,
        "compare_payload",
        lambda *_a, **_k: {
            "left_case": str(case),
            "right_case": str(tmp_path / "other"),
            "diff_count": 1,
            "diffs": [
                {
                    "rel_path": "system/controlDict",
                    "missing_in_left": ["application"],
                    "missing_in_right": [],
                    "error": None,
                },
            ],
        },
    )
    screens._knife_screen(_DummyScreen(), case)
    assert "missing_in_left" in shown[-1]


def test_knife_screen_other_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    shown = _capture_viewer(monkeypatch)
    case = tmp_path / "case"
    case.mkdir()
    messages: list[str] = []
    monkeypatch.setattr(screens, "_show_message", lambda _screen, text: messages.append(text))

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(1))
    monkeypatch.setattr(
        screens.knife_ops,
        "doctor_payload",
        lambda _case: {"lines": ["l"], "errors": ["e"], "warnings": ["w"]},
    )
    screens._knife_screen(_DummyScreen(), case)
    assert "Errors:" in shown[-1]
    assert "Warnings:" in shown[-1]

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(2))
    monkeypatch.setattr(
        screens.knife_ops,
        "status_payload",
        lambda _case: {
            "case": str(case),
            "latest_time": "3",
            "solver_error": "missing solver",
            "solver": None,
            "solver_status": None,
            "jobs_running": 0,
            "jobs_total": 0,
        },
    )
    screens._knife_screen(_DummyScreen(), case)
    assert "solver_error=missing solver" in shown[-1]

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(3))
    monkeypatch.setattr(screens, "prompt_line", lambda *_a, **_k: "")
    screens._knife_screen(_DummyScreen(), case)
    assert messages == []

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(3))
    monkeypatch.setattr(screens, "prompt_line", lambda *_a, **_k: str(case / "other"))
    monkeypatch.setattr(
        screens.knife_ops,
        "compare_payload",
        lambda *_a, **_k: {
            "left_case": str(case),
            "right_case": str(case / "other"),
            "diff_count": 1,
            "diffs": [{"rel_path": "d", "missing_in_left": [], "missing_in_right": [], "error": "bad"}],
        },
    )
    screens._knife_screen(_DummyScreen(), case)
    assert "error: bad" in shown[-1]


def test_plot_screen_residuals_empty_shows_message(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    messages: list[str] = []
    monkeypatch.setattr(screens, "_show_message", lambda _screen, text: messages.append(text))
    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(1))
    monkeypatch.setattr(screens.plot_ops, "residuals_payload", lambda _case: {"log": "x", "fields": []})

    screens._plot_screen(_DummyScreen(), case)
    assert messages == ["No residuals found in x"]


def test_plot_screen_metrics_and_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    shown = _capture_viewer(monkeypatch)
    messages: list[str] = []
    monkeypatch.setattr(screens, "_show_message", lambda _screen, text: messages.append(text))

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(
        screens.plot_ops,
        "metrics_payload",
        lambda _case: {
            "log": "log.simpleFoam",
            "times": {"count": 1, "last": 0.1},
            "courant": {"count": 1, "max": 0.2},
            "execution_time": {"count": 1, "last": 1.0},
            "residual_fields": ["U"],
        },
    )
    screens._plot_screen(_DummyScreen(), case)
    assert "residual_fields=U" in shown[-1]

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(1))
    monkeypatch.setattr(
        screens.plot_ops,
        "residuals_payload",
        lambda _case: {"log": "log.simpleFoam", "fields": [{"field": "U", "count": 1, "last": 1.0, "min": 1.0, "max": 1.0}]},
    )
    screens._plot_screen(_DummyScreen(), case)
    assert "U: count=1" in shown[-1]

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(screens.plot_ops, "metrics_payload", lambda _case: (_ for _ in ()).throw(ValueError("bad metrics")))
    screens._plot_screen(_DummyScreen(), case)
    assert messages[-1] == "bad metrics"


def test_watch_screen_jobs_and_tail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    shown = _capture_viewer(monkeypatch)

    choices = iter([0, 2])
    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(next(choices)))
    monkeypatch.setattr(
        screens.watch_ops,
        "jobs_payload",
        lambda _case, **_kwargs: {"case": str(case), "count": 1, "jobs": [{"name": "simpleFoam", "pid": 7, "status": "running"}]},
    )
    monkeypatch.setattr(
        screens.watch_ops,
        "log_tail_payload",
        lambda _case, **_kwargs: {"log": str(case / "log.simpleFoam"), "lines": ["line-1"]},
    )

    screens._watch_screen(_DummyScreen(), case)
    screens._watch_screen(_DummyScreen(), case)
    assert "simpleFoam pid=7 status=running" in shown[0]
    assert "line-1" in shown[1]


def test_watch_screen_error_and_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    shown = _capture_viewer(monkeypatch)
    messages: list[str] = []
    monkeypatch.setattr(screens, "_show_message", lambda _screen, text: messages.append(text))

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(1))
    monkeypatch.setattr(screens.watch_ops, "jobs_payload", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad jobs")))
    screens._watch_screen(_DummyScreen(), case)
    assert messages[-1] == "bad jobs"

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(
        screens.watch_ops,
        "jobs_payload",
        lambda *_a, **_k: {"case": str(case), "count": 0, "jobs": []},
    )
    screens._watch_screen(_DummyScreen(), case)
    assert "No tracked jobs." in shown[-1]


def test_run_screen_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    shown = _capture_viewer(monkeypatch)
    messages: list[str] = []
    monkeypatch.setattr(screens, "_show_message", lambda _screen, text: messages.append(text))

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(screens.run_ops, "tool_catalog_payload", lambda _case: {"tools": ["blockMesh"]})
    screens._run_screen(_DummyScreen(), case)
    assert shown and shown[-1] == "blockMesh"

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(2))
    monkeypatch.setattr(screens, "prompt_line", lambda *_a, **_k: "unknown")
    monkeypatch.setattr(screens.run_ops, "resolve_tool", lambda *_a, **_k: None)
    screens._run_screen(_DummyScreen(), case)
    assert "Unknown tool: unknown" in messages[-1]

    prompts = iter(["bad-int"])
    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(4))
    monkeypatch.setattr(screens, "prompt_line", lambda *_a, **_k: next(prompts))
    screens._run_screen(_DummyScreen(), case)
    assert "Invalid parallel value: bad-int" in messages[-1]


def test_run_screen_more_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    messages: list[str] = []
    monkeypatch.setattr(screens, "_show_message", lambda _screen, text: messages.append(text))

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(2))
    monkeypatch.setattr(screens, "prompt_line", lambda *_a, **_k: "tool")
    monkeypatch.setattr(screens.run_ops, "resolve_tool", lambda *_a, **_k: ("tool", ["echo", "ok"]))
    called: dict[str, object] = {}
    monkeypatch.setattr(
        screens,
        "_show_run_result",
        lambda _screen, _case, display, cmd, **kwargs: called.update(
            {"display": display, "cmd": cmd, "background": kwargs["background"]},
        ),
    )
    screens._run_screen(_DummyScreen(), case)
    assert called["display"] == "tool"
    assert called["background"] is False

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(3))
    monkeypatch.setattr(screens, "prompt_line", lambda *_a, **_k: "")
    monkeypatch.setattr(screens.run_ops, "solver_command", lambda *_a, **_k: ("simpleFoam", ["simpleFoam"]))
    screens._run_screen(_DummyScreen(), case)
    assert called["display"] == "simpleFoam"

    monkeypatch.setattr(screens.run_ops, "solver_command", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad solver")))
    screens._run_screen(_DummyScreen(), case)
    assert messages[-1] == "bad solver"


def test_run_screen_solver_background_calls_show_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(4))
    monkeypatch.setattr(screens, "prompt_line", lambda *_a, **_k: "8")
    monkeypatch.setattr(screens.run_ops, "solver_command", lambda *_a, **_k: ("simpleFoam", ["simpleFoam", "-parallel"]))
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        screens,
        "_show_run_result",
        lambda _screen, _case, display, cmd, **kwargs: captured.update(
            {"display": display, "cmd": cmd, "background": kwargs["background"]},
        ),
    )

    screens._run_screen(_DummyScreen(), case)
    assert captured["display"] == "simpleFoam"
    assert captured["background"] is True


def test_export_tool_catalog_json_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    messages: list[str] = []
    monkeypatch.setattr(screens, "_show_message", lambda _screen, text: messages.append(text))

    monkeypatch.setattr(screens, "prompt_line", lambda *_a, **_k: "")
    monkeypatch.setattr(screens.run_ops, "write_tool_catalog_json", lambda *_a, **_k: case / ".ofti" / "tool_catalog.json")
    monkeypatch.setattr(
        screens.run_ops,
        "tool_catalog_payload",
        lambda _case: {"case": str(case), "tools": ["blockMesh", "checkMesh"]},
    )
    screens._export_tool_catalog_json(_DummyScreen(), case)
    assert "Exported 2 tools" in messages[-1]

    monkeypatch.setattr(
        screens.run_ops,
        "tool_catalog_payload",
        lambda _case: (_ for _ in ()).throw(ValueError("bad")),
    )
    screens._export_tool_catalog_json(_DummyScreen(), case)
    assert "Exported tool catalog" in messages[-1]


def test_export_tool_catalog_json_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    messages: list[str] = []
    monkeypatch.setattr(screens, "_show_message", lambda _screen, text: messages.append(text))
    monkeypatch.setattr(screens, "prompt_line", lambda *_a, **_k: "custom.json")
    monkeypatch.setattr(
        screens.run_ops,
        "write_tool_catalog_json",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("no write")),
    )
    screens._export_tool_catalog_json(_DummyScreen(), case)
    assert "Failed to export tool catalog: no write" in messages[-1]


def test_show_run_result_background_and_foreground(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    messages: list[str] = []
    monkeypatch.setattr(screens, "_show_message", lambda _screen, text: messages.append(text))
    shown = _capture_viewer(monkeypatch)

    monkeypatch.setattr(
        screens.run_ops,
        "execute_case_command",
        lambda *_a, **_k: RunResult(0, "", "", pid=123, log_path=case / "log.simpleFoam"),
    )
    screens._show_run_result(_DummyScreen(), case, "simpleFoam", ["simpleFoam"], background=True)
    assert "pid=123" in messages[-1]

    monkeypatch.setattr(
        screens.run_ops,
        "execute_case_command",
        lambda *_a, **_k: RunResult(1, "stdout", "stderr", pid=None, log_path=None),
    )
    screens._show_run_result(_DummyScreen(), case, "simpleFoam", ["simpleFoam"], background=False)
    assert "returncode=1" in shown[-1]
    assert "stdout" in shown[-1]


def test_cli_tools_screen_wrappers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    called: list[str] = []
    monkeypatch.setattr(screens, "_knife_screen", lambda *_a, **_k: called.append("knife"))
    monkeypatch.setattr(screens, "_plot_screen", lambda *_a, **_k: called.append("plot"))
    monkeypatch.setattr(screens, "_watch_screen", lambda *_a, **_k: called.append("watch"))
    monkeypatch.setattr(screens, "_run_screen", lambda *_a, **_k: called.append("run"))
    screens.cli_knife_screen(_DummyScreen(), case)
    screens.cli_plot_screen(_DummyScreen(), case)
    screens.cli_watch_screen(_DummyScreen(), case)
    screens.cli_run_screen(_DummyScreen(), case)
    assert called == ["knife", "plot", "watch", "run"]


def test_knife_screen_value_errors_and_extended_compare(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    messages: list[str] = []
    shown = _capture_viewer(monkeypatch)
    monkeypatch.setattr(screens, "_show_message", lambda _screen, text: messages.append(text))

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(screens.knife_ops, "preflight_payload", lambda _case: (_ for _ in ()).throw(ValueError("bad preflight")))
    screens._knife_screen(_DummyScreen(), case)
    assert messages[-1] == "bad preflight"

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(1))
    monkeypatch.setattr(screens.knife_ops, "doctor_payload", lambda _case: (_ for _ in ()).throw(ValueError("bad doctor")))
    screens._knife_screen(_DummyScreen(), case)
    assert messages[-1] == "bad doctor"

    monkeypatch.setattr(
        screens.knife_ops,
        "doctor_payload",
        lambda _case: {"lines": ["line"], "errors": [], "warnings": []},
    )
    screens._knife_screen(_DummyScreen(), case)
    assert "OK: no issues found." in shown[-1]

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(2))
    monkeypatch.setattr(screens.knife_ops, "status_payload", lambda _case: (_ for _ in ()).throw(ValueError("bad status")))
    screens._knife_screen(_DummyScreen(), case)
    assert messages[-1] == "bad status"

    monkeypatch.setattr(
        screens.knife_ops,
        "status_payload",
        lambda _case: {
            "case": str(case),
            "latest_time": "4",
            "latest_iteration": 10,
            "latest_delta_t": 0.1,
            "sec_per_iter": 1.0,
            "solver_error": None,
            "solver": "simpleFoam",
            "solver_status": "running",
            "run_time_control": {"criteria": [], "passed": 0, "failed": 0, "unknown": 0},
            "eta_seconds_to_criteria_start": None,
            "eta_seconds_to_end_time": None,
            "log_path": "log.simpleFoam",
            "log_fresh": True,
            "running": True,
            "tracked_solver_processes": [{"pid": 1}],
            "untracked_solver_processes": [{"pid": 2}],
            "jobs_running": 1,
            "jobs_total": 1,
        },
    )
    screens._knife_screen(_DummyScreen(), case)
    status_text = shown[-1]
    assert "solver=simpleFoam" in status_text
    assert "tracked_solver_processes=1" in status_text
    assert "untracked_solver_processes=1" in status_text

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(3))
    monkeypatch.setattr(screens, "prompt_line", lambda *_a, **_k: str(case / "other"))
    monkeypatch.setattr(screens.knife_ops, "compare_payload", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad compare")))
    screens._knife_screen(_DummyScreen(), case)
    assert messages[-1] == "bad compare"

    monkeypatch.setattr(
        screens.knife_ops,
        "compare_payload",
        lambda *_a, **_k: {
            "left_case": str(case),
            "right_case": str(case / "other"),
            "diff_count": 1,
            "diffs": [
                {
                    "rel_path": "system/controlDict",
                    "kind": "dict",
                    "error": None,
                    "missing_in_left": [],
                    "missing_in_right": ["application"],
                    "value_diffs": [{"key": f"k{idx}", "left": str(idx), "right": str(idx + 1)} for idx in range(21)],
                    "left_hash": "aaa",
                    "right_hash": "bbb",
                },
            ],
        },
    )
    screens._knife_screen(_DummyScreen(), case)
    compare_text = shown[-1]
    assert "missing_in_right: application" in compare_text
    assert "value_diff k0" in compare_text
    assert "value_diff_more=1" in compare_text
    assert "left_hash=aaa" in compare_text


def test_plot_watch_run_and_export_error_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    messages: list[str] = []
    monkeypatch.setattr(screens, "_show_message", lambda _screen, text: messages.append(text))

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(2))
    screens._plot_screen(_DummyScreen(), case)

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(1))
    monkeypatch.setattr(screens.plot_ops, "residuals_payload", lambda _case: (_ for _ in ()).throw(ValueError("plot bad")))
    screens._plot_screen(_DummyScreen(), case)
    assert messages[-1] == "plot bad"

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(3))
    screens._watch_screen(_DummyScreen(), case)

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(2))
    monkeypatch.setattr(screens.watch_ops, "log_tail_payload", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("watch bad")))
    screens._watch_screen(_DummyScreen(), case)
    assert messages[-1] == "watch bad"

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(screens.run_ops, "tool_catalog_payload", lambda _case: (_ for _ in ()).throw(ValueError("catalog bad")))
    screens._run_screen(_DummyScreen(), case)
    assert messages[-1] == "catalog bad"

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(2))
    monkeypatch.setattr(screens, "prompt_line", lambda *_a, **_k: "")
    screens._run_screen(_DummyScreen(), case)

    monkeypatch.setattr(screens, "prompt_line", lambda *_a, **_k: "tool")
    monkeypatch.setattr(screens.run_ops, "resolve_tool", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("resolve bad")))
    screens._run_screen(_DummyScreen(), case)
    assert messages[-1] == "resolve bad"

    called: list[str] = []
    monkeypatch.setattr(screens, "_export_tool_catalog_json", lambda *_a, **_k: called.append("export"))
    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(1))
    screens._run_screen(_DummyScreen(), case)
    assert called == ["export"]

    monkeypatch.setattr(screens, "prompt_line", lambda *_a, **_k: None)
    screens._export_tool_catalog_json(_DummyScreen(), case)


def test_cli_tools_screen_return_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    shown = _capture_viewer(monkeypatch)

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(-1))
    screens._knife_screen(_DummyScreen(), case)
    screens._run_screen(_DummyScreen(), case)

    monkeypatch.setattr(screens, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(
        screens.knife_ops,
        "preflight_payload",
        lambda _case: {
            "case": str(case),
            "checks": {"system/controlDict": True},
            "solver_error": "missing app",
            "ok": False,
        },
    )
    screens._knife_screen(_DummyScreen(), case)
    assert "solver_error=missing app" in shown[-1]


def test_export_tool_catalog_json_none_input(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    messages: list[str] = []
    monkeypatch.setattr(screens, "_show_message", lambda _screen, text: messages.append(text))
    monkeypatch.setattr(screens, "prompt_line", lambda *_a, **_k: None)
    screens._export_tool_catalog_json(_DummyScreen(), case)
    assert messages == []

from __future__ import annotations

from pathlib import Path

import pytest

from ofti.tools import logs_analysis
from tests.testscreen import TestScreen as _Screen


def _capture_viewer(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    shown: list[str] = []

    class _Viewer:
        def __init__(self, _screen: object, text: str) -> None:
            shown.append(text)

        def display(self) -> None:
            return None

    monkeypatch.setattr(logs_analysis, "Viewer", _Viewer)
    return shown


def test_residual_timeline_screen_none_and_read_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    screen = _Screen()
    shown = _capture_viewer(monkeypatch)
    messages: list[str] = []
    monkeypatch.setattr(logs_analysis, "_show_message", lambda _s, text: messages.append(text))

    monkeypatch.setattr(logs_analysis, "_select_solver_log_file", lambda *_a, **_k: None)
    logs_analysis.residual_timeline_screen(screen, tmp_path)
    assert shown == []

    missing = tmp_path / "log.simpleFoam"
    monkeypatch.setattr(logs_analysis, "_select_solver_log_file", lambda *_a, **_k: missing)
    logs_analysis.residual_timeline_screen(screen, tmp_path)
    assert "Failed to read log.simpleFoam" in messages[-1]


def test_residual_timeline_screen_no_residuals_and_render(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    screen = _Screen(width=120)
    shown = _capture_viewer(monkeypatch)
    messages: list[str] = []
    monkeypatch.setattr(logs_analysis, "_show_message", lambda _s, text: messages.append(text))

    empty_log = tmp_path / "log.empty"
    empty_log.write_text("Time = 0.1\nExecutionTime = 1 s\n")
    monkeypatch.setattr(logs_analysis, "_select_solver_log_file", lambda *_a, **_k: empty_log)
    logs_analysis.residual_timeline_screen(screen, tmp_path)
    assert messages[-1] == "No residuals found in log.empty."

    solver_log = tmp_path / "log.hy2Foam"
    solver_log.write_text(
        "\n".join(
            [
                "Time = 0.1",
                "Courant Number mean: 0.1 max: 0.6",
                "ExecutionTime = 1.2 s",
                "Solving for Ux, Initial residual = 1e-2, Final residual = 5e-3, No Iterations 2",
                "Solving for Ux, Initial residual = 5e-3, Final residual = 2e-3, No Iterations 2",
            ],
        ),
    )
    monkeypatch.setattr(logs_analysis, "_select_solver_log_file", lambda *_a, **_k: solver_log)
    logs_analysis.residual_timeline_screen(screen, tmp_path)
    rendered = shown[-1]
    assert "Residuals summary" in rendered
    assert "Max Courant" in rendered
    assert "Execution time:" in rendered
    assert "Ux" in rendered


def test_log_analysis_screen_none_read_error_no_metrics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    screen = _Screen()
    shown = _capture_viewer(monkeypatch)
    messages: list[str] = []
    monkeypatch.setattr(logs_analysis, "_show_message", lambda _s, text: messages.append(text))

    monkeypatch.setattr(logs_analysis, "_select_solver_log_file", lambda *_a, **_k: None)
    logs_analysis.log_analysis_screen(screen, tmp_path)
    assert shown == []

    missing = tmp_path / "log.simpleFoam"
    monkeypatch.setattr(logs_analysis, "_select_solver_log_file", lambda *_a, **_k: missing)
    logs_analysis.log_analysis_screen(screen, tmp_path)
    assert "Failed to read log.simpleFoam" in messages[-1]

    plain = tmp_path / "log.plain"
    plain.write_text("just text\n")
    monkeypatch.setattr(logs_analysis, "_select_solver_log_file", lambda *_a, **_k: plain)
    logs_analysis.log_analysis_screen(screen, tmp_path)
    assert messages[-1] == "No metrics found in log.plain."


def test_log_analysis_screen_render(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    screen = _Screen(width=120)
    shown = _capture_viewer(monkeypatch)

    solver_log = tmp_path / "log.simpleFoam"
    solver_log.write_text(
        "\n".join(
            [
                "Time = 0.1",
                "Courant Number mean: 0.1 max: 0.2",
                "ExecutionTime = 1.0 s",
                "Time = 0.2",
                "Courant Number mean: 0.1 max: 0.4",
                "ExecutionTime = 1.8 s",
                "Solving for p, Initial residual = 1e-3, Final residual = 1e-6, No Iterations 2",
            ],
        ),
    )
    monkeypatch.setattr(logs_analysis, "_select_solver_log_file", lambda *_a, **_k: solver_log)
    logs_analysis.log_analysis_screen(screen, tmp_path)
    rendered = shown[-1]
    assert "LOG ANALYSIS" in rendered
    assert "Courant trend:" in rendered
    assert "Step trend:" in rendered
    assert "Residuals:" in rendered


def test_sparkline_handles_edge_cases() -> None:
    assert logs_analysis._sparkline([], width=5) == ""
    assert logs_analysis._sparkline([0.1, 0.2], width=0) == ""

    line = logs_analysis._sparkline([0.0, 1e-12, 1e2, 1e4, 1e6], width=3)
    assert len(line) == 3

    flat = logs_analysis._sparkline([1.0, 1.0, 1.0], width=5)
    assert flat == "@@@"

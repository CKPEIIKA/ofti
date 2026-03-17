from __future__ import annotations

from pathlib import Path

import pytest

from ofti.app.menus import case_tools


class _Viewer:
    def __init__(self, _stdscr: object, text: str) -> None:
        self.text = text

    def display(self) -> None:
        return None


def test_show_preflight_and_status_screens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []
    monkeypatch.setattr(case_tools, "Viewer", lambda stdscr, text: captured.append(text) or _Viewer(stdscr, text))
    monkeypatch.setattr(
        case_tools.knife_ops,
        "preflight_payload",
        lambda _case: {
            "case": str(tmp_path),
            "checks": {"controlDict": True, "fvSchemes": False},
            "solver_error": None,
            "ok": False,
        },
    )
    case_tools.show_preflight_screen(object(), tmp_path)
    assert "controlDict=ok" in captured[-1]
    assert "fvSchemes=missing" in captured[-1]

    monkeypatch.setattr(case_tools.knife_ops, "status_payload", lambda _case: {"case": str(tmp_path)})
    monkeypatch.setattr(case_tools.status_render_service, "case_status_lines", lambda _payload: ["status-ok"])
    case_tools.show_case_status_screen(object(), tmp_path)
    assert captured[-1] == "status-ok"


def test_show_current_jobs_screen_typeerror_fallback_and_truncate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []
    monkeypatch.setattr(case_tools, "Viewer", lambda stdscr, text: captured.append(text) or _Viewer(stdscr, text))

    rows = [
        {
            "pid": idx,
            "role": "solver",
            "solver": "hy2Foam",
            "launcher_pid": None,
            "command": "hy2Foam -parallel",
        }
        for idx in range(100, 141)
    ]

    def _current(_case: Path) -> dict[str, object]:
        return {
            "case": str(tmp_path),
            "solver": "hy2Foam",
            "solver_error": None,
            "jobs_running": 2,
            "jobs": [{"id": "job-1", "pid": 10, "name": "hy2Foam", "status": "running"}],
            "untracked_processes": rows,
        }

    monkeypatch.setattr(case_tools.knife_ops, "current_payload", _current)
    case_tools.show_current_jobs_screen(object(), tmp_path)
    text = captured[-1]
    assert "tracked_jobs:" in text
    assert "untracked_processes:" in text
    assert "... 1 more" in text


def test_adopt_untracked_screen_and_error_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []
    messages: list[str] = []
    monkeypatch.setattr(case_tools, "Viewer", lambda stdscr, text: captured.append(text) or _Viewer(stdscr, text))
    monkeypatch.setattr(case_tools, "show_message", lambda _stdscr, message: messages.append(message))

    monkeypatch.setattr(
        case_tools.knife_ops,
        "adopt_payload",
        lambda _case, **_kwargs: {
            "case": str(tmp_path),
            "scope": "case",
            "selected": 1,
            "adopted": [{"id": "x", "pid": 10, "case": str(tmp_path), "name": "hy2Foam", "role": "solver"}],
            "failed": [{"pid": 11, "case": str(tmp_path), "error": "bad"}],
            "jobs_running_before": 0,
            "jobs_running_after": 1,
        },
    )
    case_tools.adopt_untracked_screen(object(), tmp_path)
    assert "adopted_rows:" in captured[-1]
    assert "failed:" in captured[-1]

    monkeypatch.setattr(
        case_tools.knife_ops,
        "adopt_payload",
        lambda _case, **_kwargs: (_ for _ in ()).throw(ValueError("adopt-broken")),
    )
    case_tools.adopt_untracked_screen(object(), tmp_path)
    assert messages[-1] == "adopt-broken"


def test_compare_dictionaries_screen_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []
    messages: list[str] = []
    monkeypatch.setattr(case_tools, "Viewer", lambda stdscr, text: captured.append(text) or _Viewer(stdscr, text))
    monkeypatch.setattr(case_tools, "show_message", lambda _stdscr, message: messages.append(message))

    monkeypatch.setattr(case_tools, "prompt_line", lambda _stdscr, _prompt: "")
    case_tools.compare_dictionaries_screen(object(), tmp_path)
    assert captured == []

    monkeypatch.setattr(case_tools, "prompt_line", lambda _stdscr, _prompt: str(tmp_path / "other"))
    monkeypatch.setattr(
        case_tools.knife_ops,
        "compare_payload",
        lambda _left, _right: {
            "left_case": "a",
            "right_case": "b",
            "diff_count": 1,
            "diffs": [
                {
                    "rel_path": "system/controlDict",
                    "error": None,
                    "missing_in_left": [],
                    "missing_in_right": [],
                    "value_diffs": [{"key": "application", "left": "a", "right": "b"}],
                },
            ],
        },
    )
    case_tools.compare_dictionaries_screen(object(), tmp_path)
    assert "diff_count=1" in captured[-1]
    assert "application: left=a right=b" in captured[-1]

    monkeypatch.setattr(
        case_tools.knife_ops,
        "compare_payload",
        lambda _left, _right: (_ for _ in ()).throw(ValueError("compare-broken")),
    )
    case_tools.compare_dictionaries_screen(object(), tmp_path)
    assert messages[-1] == "compare-broken"


def test_initials_and_set_entry_screens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []
    messages: list[str] = []
    monkeypatch.setattr(case_tools, "Viewer", lambda stdscr, text: captured.append(text) or _Viewer(stdscr, text))
    monkeypatch.setattr(case_tools, "show_message", lambda _stdscr, message: messages.append(message))

    monkeypatch.setattr(
        case_tools.knife_ops,
        "initials_payload",
        lambda _case: {
            "case": str(tmp_path),
            "initial_dir": str(tmp_path / "0"),
            "field_count": 1,
            "patch_count": 1,
            "fields": [
                {
                    "name": "U",
                    "internal_field": "uniform (1 0 0)",
                    "boundary": {"inlet": {"type": "fixedValue", "value": "uniform (1 0 0)"}},
                },
            ],
        },
    )
    case_tools.show_initial_fields_screen(object(), tmp_path)
    assert "fields=1 patches=1" in captured[-1]
    assert "- inlet: type=fixedValue value=uniform (1 0 0)" in captured[-1]

    prompts = iter(["system/controlDict", "application", "hy2Foam"])
    monkeypatch.setattr(case_tools, "prompt_line", lambda _stdscr, _prompt: next(prompts))
    monkeypatch.setattr(
        case_tools.knife_ops,
        "set_entry_payload",
        lambda _case, rel_file, key, value: {
            "case": str(tmp_path),
            "file": str(tmp_path / rel_file),
            "key": key,
            "value": value,
            "ok": True,
        },
    )
    case_tools.set_dictionary_entry_screen(object(), tmp_path)
    assert "ok=True" in captured[-1]

    prompts = iter(["system/controlDict", "application", "bad"])
    monkeypatch.setattr(case_tools, "prompt_line", lambda _stdscr, _prompt: next(prompts))
    monkeypatch.setattr(
        case_tools.knife_ops,
        "set_entry_payload",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("set-broken")),
    )
    case_tools.set_dictionary_entry_screen(object(), tmp_path)
    assert messages[-1] == "set-broken"


def test_runtime_diagnostic_screens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []
    messages: list[str] = []
    monkeypatch.setattr(case_tools, "Viewer", lambda stdscr, text: captured.append(text) or _Viewer(stdscr, text))
    monkeypatch.setattr(case_tools, "show_message", lambda _stdscr, message: messages.append(message))

    monkeypatch.setattr(
        case_tools.knife_ops,
        "criteria_payload",
        lambda _case: {
            "case": str(tmp_path),
            "solver": "hy2Foam",
            "criteria_count": 1,
            "passed": 1,
            "failed": 0,
            "unknown": 0,
            "criteria": [
                {"name": "residual", "met": True, "value": 1e-5, "tol": 1e-4, "unmet": "", "source": "controlDict"},
            ],
        },
    )
    case_tools.show_runtime_criteria_screen(object(), tmp_path)
    assert "criteria=1 pass=1 fail=0 unknown=0" in captured[-1]

    monkeypatch.setattr(case_tools, "prompt_line", lambda _stdscr, _prompt: "invalid")
    case_tools.show_eta_forecast_screen(object(), tmp_path)
    assert "Unsupported ETA mode" in messages[-1]

    monkeypatch.setattr(case_tools, "prompt_line", lambda _stdscr, _prompt: "auto")
    monkeypatch.setattr(
        case_tools.knife_ops,
        "eta_payload",
        lambda _case, mode: {
            "case": str(tmp_path),
            "mode": mode,
            "eta_mode": "criteria",
            "eta_reason": "criteria_trend",
            "eta_confidence": 0.9,
            "eta_seconds": 120.0,
            "eta_criteria_seconds": 120.0,
            "eta_end_time_seconds": 300.0,
        },
    )
    case_tools.show_eta_forecast_screen(object(), tmp_path)
    assert "eta_seconds=120.0" in captured[-1]

    monkeypatch.setattr(case_tools.knife_ops, "report_payload", lambda _case: {"case": str(tmp_path)})
    monkeypatch.setattr(case_tools.knife_ops, "report_markdown", lambda _payload: "# report")
    case_tools.show_runtime_report_screen(object(), tmp_path)
    assert captured[-1] == "# report"

    monkeypatch.setattr(case_tools, "prompt_line", lambda _stdscr, _prompt: "n")
    monkeypatch.setattr(
        case_tools.knife_ops,
        "converge_payload",
        lambda *_a, **_k: {
            "log": "log.hy2Foam",
            "shock": {"drift": 0.0, "limit": 0.02, "ok": True},
            "drag": {"band": 0.0, "limit": 0.02, "ok": True},
            "mass": {"last_abs_global": 0.0, "limit": 1e-4, "ok": True},
            "residuals": {"flatline": False, "flatline_fields": []},
            "thermo": {"out_of_range_count": 0, "ok": True},
            "strict": False,
            "strict_ok": True,
            "ok": True,
        },
    )
    case_tools.run_convergence_check_screen(object(), tmp_path)
    assert "ok=True" in captured[-1]

    prompts = iter(["Courant Number mean", "0.02", "50", "0", "le"])
    monkeypatch.setattr(case_tools, "prompt_line", lambda _stdscr, _prompt: next(prompts))
    monkeypatch.setattr(
        case_tools.knife_ops,
        "stability_payload",
        lambda *_a, **_k: {
            "log": "log.hy2Foam",
            "pattern": "Courant Number mean",
            "count": 100,
            "window": 50,
            "window_delta": 0.01,
            "tolerance": 0.02,
            "comparator": "le",
            "latest": 0.2,
            "status": "pass",
            "unmet_reason": "",
            "eta_seconds": 0.0,
        },
    )
    case_tools.run_stability_check_screen(object(), tmp_path)
    assert "status=pass" in captured[-1]

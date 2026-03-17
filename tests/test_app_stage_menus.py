from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ofti.app.menus.config import config_menu
from ofti.app.menus.physics import physics_menu
from ofti.app.menus.postprocessing import postprocessing_menu
from ofti.app.menus.simulation import simulation_menu
from ofti.app.screens import main as main_screen
from ofti.app.state import AppState, Screen


def _label_sequence(labels: list[str]):
    queue = list(labels)

    def _menu_choice(_stdscr, _title, options, *_args, **_kwargs):
        if not queue:
            return -1
        label = queue.pop(0)
        return options.index(label)

    return _menu_choice


def test_main_menu_no_tools_option(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("application simpleFoam;\n")
    captured: dict[str, list[str]] = {}

    class _RootMenu:
        def __init__(self, _stdscr, _title, options, **_kwargs):
            captured["options"] = list(options)

        def navigate(self) -> int:
            return -1

    monkeypatch.setattr(main_screen, "RootMenu", _RootMenu)
    result = main_screen.main_menu_screen(
        stdscr=object(),
        case_path=case,
        state=AppState(),
        command_callbacks=SimpleNamespace(),
        editor_screen=lambda *_a, **_k: None,
        check_syntax_screen=lambda *_a, **_k: None,
        global_search_screen=lambda *_a, **_k: None,
    )
    assert result is None
    assert "Tools" not in captured["options"]


def test_simulation_menu_stage_actions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("application hy2Foam;\n")
    (case / "system" / "decomposeParDict").write_text("numberOfSubdomains 2;\n")
    calls: list[str] = []

    monkeypatch.setattr(
        "ofti.app.menus.simulation.menu_choice",
        _label_sequence(
            [
                "Case status",
                "Current jobs (live)",
                "Runtime criteria",
                "ETA forecast",
                "Runtime report",
                "Convergence check",
                "Stability check",
                "Adopt untracked processes",
                "Stop tracked job",
                "Pause tracked job",
                "Resume tracked job",
                "Back",
            ],
        ),
    )
    monkeypatch.setattr("ofti.app.menus.simulation.solver_job_running", lambda _case: False)
    monkeypatch.setattr("ofti.app.menus.simulation.solver_status_line", lambda _case: "idle")
    monkeypatch.setattr("ofti.app.menus.simulation.show_case_status_screen", lambda *_a, **_k: calls.append("status"))
    monkeypatch.setattr("ofti.app.menus.simulation.show_current_jobs_screen", lambda *_a, **_k: calls.append("current"))
    monkeypatch.setattr("ofti.app.menus.simulation.show_runtime_criteria_screen", lambda *_a, **_k: calls.append("criteria"))
    monkeypatch.setattr("ofti.app.menus.simulation.show_eta_forecast_screen", lambda *_a, **_k: calls.append("eta"))
    monkeypatch.setattr("ofti.app.menus.simulation.show_runtime_report_screen", lambda *_a, **_k: calls.append("report"))
    monkeypatch.setattr("ofti.app.menus.simulation.run_convergence_check_screen", lambda *_a, **_k: calls.append("converge"))
    monkeypatch.setattr("ofti.app.menus.simulation.run_stability_check_screen", lambda *_a, **_k: calls.append("stability"))
    monkeypatch.setattr("ofti.app.menus.simulation.adopt_untracked_screen", lambda *_a, **_k: calls.append("adopt"))
    monkeypatch.setattr("ofti.app.menus.simulation.stop_job_screen", lambda *_a, **_k: calls.append("stop"))
    monkeypatch.setattr("ofti.app.menus.simulation.pause_job_screen", lambda *_a, **_k: calls.append("pause"))
    monkeypatch.setattr("ofti.app.menus.simulation.resume_job_screen", lambda *_a, **_k: calls.append("resume"))

    assert simulation_menu(object(), case, AppState()) == Screen.MAIN_MENU
    assert calls == [
        "status",
        "current",
        "criteria",
        "eta",
        "report",
        "converge",
        "stability",
        "adopt",
        "stop",
        "pause",
        "resume",
    ]


def test_config_menu_case_ops_actions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    calls: list[str] = []

    monkeypatch.setattr(
        "ofti.app.menus.config.menu_choice",
        _label_sequence(
            [
                "Preflight checks",
                "Case doctor",
                "Case status",
                "Initial fields summary",
                "Set dictionary entry",
                "Compare dictionaries",
                "Clone case",
                "Back",
            ],
        ),
    )
    monkeypatch.setattr("ofti.app.menus.config.show_preflight_screen", lambda *_a, **_k: calls.append("preflight"))
    monkeypatch.setattr("ofti.app.menus.config.case_doctor_screen", lambda *_a, **_k: calls.append("doctor"))
    monkeypatch.setattr("ofti.app.menus.config.show_case_status_screen", lambda *_a, **_k: calls.append("status"))
    monkeypatch.setattr("ofti.app.menus.config.show_initial_fields_screen", lambda *_a, **_k: calls.append("initials"))
    monkeypatch.setattr("ofti.app.menus.config.set_dictionary_entry_screen", lambda *_a, **_k: calls.append("set"))
    monkeypatch.setattr(
        "ofti.app.menus.config.compare_dictionaries_screen",
        lambda *_a, **_k: calls.append("compare"),
    )
    monkeypatch.setattr("ofti.app.menus.config.clone_case", lambda *_a, **_k: calls.append("clone"))

    assert (
        config_menu(
            stdscr=object(),
            case_path=case,
            state=AppState(),
            has_fzf=True,
            editor_screen=lambda *_a, **_k: calls.append("editor"),
            check_syntax_screen=lambda *_a, **_k: calls.append("check"),
            openfoam_env_screen=lambda *_a, **_k: calls.append("env"),
            global_search_screen=lambda *_a, **_k: calls.append("search"),
        )
        == Screen.MAIN_MENU
    )
    assert calls == ["preflight", "doctor", "status", "initials", "set", "compare", "clone"]


def test_physics_menu_high_speed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    calls: list[str] = []
    monkeypatch.setattr(
        "ofti.app.menus.physics.menu_choice",
        _label_sequence(["High-speed helper", "Back"]),
    )
    monkeypatch.setattr(
        "ofti.app.menus.physics.high_speed_helper_screen",
        lambda *_a, **_k: calls.append("high"),
    )
    assert (
        physics_menu(
            stdscr=object(),
            case_path=case,
            state=AppState(),
            editor_screen=lambda *_a, **_k: calls.append("editor"),
            check_syntax_screen=lambda *_a, **_k: calls.append("check"),
        )
        == Screen.MAIN_MENU
    )
    assert calls == ["high"]


def test_postprocessing_menu_yplus(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    calls: list[str] = []
    monkeypatch.setattr(
        "ofti.app.menus.postprocessing.menu_choice",
        _label_sequence(["yPlus estimator", "Back"]),
    )
    monkeypatch.setattr("ofti.app.menus.postprocessing.yplus_screen", lambda *_a, **_k: calls.append("yplus"))
    assert postprocessing_menu(object(), case, AppState()) == Screen.MAIN_MENU
    assert calls == ["yplus"]


def test_simulation_menu_disables_parametric_without_preprocessing_extras(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("application hy2Foam;\n")
    (case / "system" / "decomposeParDict").write_text("numberOfSubdomains 2;\n")
    captured: dict[str, object] = {}

    def _menu_choice(*_args, **kwargs):
        captured["disabled"] = set(kwargs.get("disabled_indices", set()))
        captured["reasons"] = dict(kwargs.get("disabled_reasons", {}))
        return -1

    monkeypatch.setattr("ofti.app.menus.simulation.preprocessing_available", lambda: False)
    monkeypatch.setattr("ofti.app.menus.simulation.menu_choice", _menu_choice)
    monkeypatch.setattr("ofti.app.menus.simulation.solver_job_running", lambda _case: False)
    monkeypatch.setattr("ofti.app.menus.simulation.solver_status_line", lambda _case: "idle")
    assert simulation_menu(object(), case, AppState()) == Screen.MAIN_MENU
    disabled = captured["disabled"]
    assert isinstance(disabled, set)
    assert 18 in disabled
    reasons = captured["reasons"]
    assert isinstance(reasons, dict)
    assert "preprocessing extras" in str(reasons[18])


def test_postprocessing_menu_disables_tables_without_postprocessing_extras(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    captured: dict[str, object] = {}

    def _menu_choice(*_args, **kwargs):
        captured["disabled"] = set(kwargs.get("disabled_indices", set()))
        captured["reasons"] = dict(kwargs.get("disabled_reasons", {}))
        return -1

    monkeypatch.setattr("ofti.app.menus.postprocessing.postprocessing_tables_available", lambda: False)
    monkeypatch.setattr("ofti.app.menus.postprocessing.menu_choice", _menu_choice)
    assert postprocessing_menu(object(), case, AppState()) == Screen.MAIN_MENU
    disabled = captured["disabled"]
    assert isinstance(disabled, set)
    assert 5 in disabled
    reasons = captured["reasons"]
    assert isinstance(reasons, dict)
    assert "postprocessing extras" in str(reasons[5])

from __future__ import annotations

import types
from pathlib import Path

import pytest

from ofti.foamlib import adapter as foamlib_integration
from ofti.tools import (
    logs_analysis,
    logs_fields,
    logs_probes,
    logs_view,
    pipeline,
    postprocessing,
    reconstruct,
    run,
)
from ofti.tools.case_ops import open_paraview_screen
from ofti.tools.diagnostics import case_report_screen
from ofti.tools.job_control import run_tool_background_screen, stop_job_screen
from ofti.tools.run import run_checkmesh, run_decomposepar
from ofti.tools.solver import run_current_solver_live
from ofti.tools.solver_control import safe_stop_screen, solver_resurrection_screen
from ofti.tools.time_pruner import time_directory_pruner_screen
from ofti.tools.tool_dicts_prompts import set_fields_prompt
from ofti.tools.yplus import yplus_screen
from ofti.ui_curses.viewer import Viewer
from tests.testscreen import TestScreen as FakeScreen


def test_case_report_screen(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;\n")
    monkeypatch.setattr(Viewer, "display", lambda *_: None)
    case_report_screen(FakeScreen(), case_dir)


def test_logs_screen_and_tail(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    log_path = case_dir / "log.simpleFoam"
    log_path.write_text("Time = 0.1\n")
    pick = iter([log_path, None])
    monkeypatch.setattr(
        "ofti.tools.logs_view._select_log_file",
        lambda *_a, **_k: next(pick),
    )
    monkeypatch.setattr(Viewer, "display", lambda *_: None)
    choices = iter([0, 3])
    monkeypatch.setattr("ofti.ui_curses.menus.Menu.navigate", lambda *_: next(choices))
    logs_view.logs_screen(FakeScreen(), case_dir)

    monkeypatch.setattr("ofti.ui_curses.menus.Menu.navigate", lambda *_: 0)
    logs_view.log_tail_screen(FakeScreen(keys=[ord("h")]), case_dir)


def test_logs_screen_analysis_shortcut(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    called: dict[str, bool] = {}
    choices = iter([2, 3])
    monkeypatch.setattr("ofti.ui_curses.menus.Menu.navigate", lambda *_: next(choices))
    monkeypatch.setattr(
        "ofti.tools.logs_view.log_analysis_screen",
        lambda *_a, **_k: called.__setitem__("analysis", True),
    )
    logs_view.logs_screen(FakeScreen(), case_dir)
    assert called.get("analysis") is True


def test_log_analysis_and_residuals(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    log_path = case_dir / "log.simpleFoam"
    log_path.write_text(
        "\n".join(
            [
                "Time = 0.1",
                "Courant Number mean: 0.1 max: 0.2",
                "ExecutionTime = 1 s ClockTime = 1 s",
                "Solving for Ux, Initial residual = 1e-3, Final residual = 1e-6",
            ],
        ),
    )
    monkeypatch.setattr(
        "ofti.tools.logs_select._select_solver_log_file",
        lambda *_a, **_k: log_path,
    )
    monkeypatch.setattr(Viewer, "display", lambda *_: None)
    logs_analysis.log_analysis_screen(FakeScreen(), case_dir)
    logs_analysis.residual_timeline_screen(FakeScreen(), case_dir)


def test_run_checkmesh_and_decompose(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "decomposeParDict").write_text("numberOfSubdomains 2;\n")
    completed = types.SimpleNamespace(returncode=0, stdout="Mesh OK", stderr="")
    monkeypatch.setattr("ofti.tools.run.run_tool_command_capture", lambda *_a, **_k: completed)
    monkeypatch.setattr("ofti.tools.run.run_tool_command", lambda *_a, **_k: None)
    monkeypatch.setattr(Viewer, "display", lambda *_: None)
    run_checkmesh(FakeScreen(keys=[ord("h")]), case_dir)
    run_decomposepar(FakeScreen(), case_dir)


def test_run_current_solver_live(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;\n")
    zero_dir = case_dir / "0"
    zero_dir.mkdir()
    (zero_dir / "U").write_text("internalField uniform (0 0 0);\n")
    (zero_dir / "p").write_text("internalField uniform 0;\n")
    called = {}
    monkeypatch.setattr("ofti.tools.solver.resolve_openfoam_bashrc", lambda: None)
    monkeypatch.setattr("ofti.tools.solver.require_wm_project_dir", lambda *_: None)
    monkeypatch.setattr("ofti.core.solver_checks.read_entry", lambda *_a, **_k: "simpleFoam;")
    monkeypatch.setattr(
        "ofti.tools.solver._run_solver_live_cmd",
        lambda *_a, **_k: called.setdefault("run", True),
    )
    run_current_solver_live(FakeScreen(), case_dir)
    assert called.get("run") is True


def test_solver_controls(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;\n")
    (case_dir / "1").mkdir()
    safe_stop_screen(FakeScreen(), case_dir)
    assert (case_dir / "stop").is_file()
    monkeypatch.setattr("ofti.tools.solver_control.set_start_from_latest", lambda *_: True)
    solver_resurrection_screen(FakeScreen(), case_dir)


@pytest.mark.skipif(
    not foamlib_integration.available(),
    reason="foamlib required for field summary screen",
)
def test_field_summary_screen(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "1").mkdir(parents=True)
    field = case_dir / "1" / "T"
    field.write_text(
        "\n".join(
            [
                "FoamFile",
                "{",
                "    version 2.0;",
                "    format ascii;",
                "    class volScalarField;",
                "    location \"1\";",
                "    object T;",
                "}",
                "internalField uniform 1;",
                "boundaryField{}",
            ],
        ),
    )
    monkeypatch.setattr("ofti.ui_curses.menus.Menu.navigate", lambda *_: 0)
    monkeypatch.setattr(Viewer, "display", lambda *_: None)
    logs_fields.field_summary_screen(FakeScreen(), case_dir)


def test_postprocessing_and_probes(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    root = case_dir / "postProcessing" / "probes" / "0"
    root.mkdir(parents=True)
    probe = root / "U"
    probe.write_text("0.1 (1 0 0)\n0.2 (2 0 0)\n")
    monkeypatch.setattr("ofti.ui_curses.menus.Menu.navigate", lambda *_: 0)
    monkeypatch.setattr(Viewer, "display", lambda *_: None)
    logs_probes.probes_viewer_screen(FakeScreen(), case_dir)
    postprocessing.postprocessing_browser_screen(FakeScreen(keys=[ord("h")]), case_dir)


def test_time_pruner_and_setfields(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "0").mkdir(parents=True)
    (case_dir / "1").mkdir(parents=True)
    (case_dir / "2").mkdir(parents=True)
    monkeypatch.setattr("ofti.tools.time_pruner.prompt_line", lambda *_: "2")
    time_directory_pruner_screen(FakeScreen(), case_dir)

    (case_dir / "system").mkdir(exist_ok=True)
    (case_dir / "system" / "setFieldsDict").write_text("defaultFieldValues();\n")
    monkeypatch.setattr("ofti.tools.tool_dicts_prompts._run_simple_tool", lambda *_: None)
    monkeypatch.setattr("ofti.tools.tool_dicts_prompts.prompt_args_line", lambda *_: [])
    set_fields_prompt(FakeScreen(), case_dir)


def test_yplus_screen(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    monkeypatch.setattr(
        "ofti.tools.yplus._run_tool_capture",
        lambda *_a, **_k: ("y+ min 1 max 2 avg 1.5", ""),
    )
    yplus_screen(FakeScreen(keys=[ord("h")]), case_dir)


def test_job_control_screens(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    monkeypatch.setattr("ofti.ui_curses.menus.Menu.navigate", lambda *_: -1)
    run_tool_background_screen(FakeScreen(), case_dir)
    stop_job_screen(FakeScreen(), case_dir)


def test_open_paraview_screen(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    monkeypatch.setattr("shutil.which", lambda *_: None)
    open_paraview_screen(FakeScreen(), case_dir)


def test_pipeline_editor_and_sampling(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    pipeline_path = case_dir / "Allrun"
    pipeline_path.write_text("\n".join(["#!/bin/bash", pipeline.PIPELINE_HEADER]))
    monkeypatch.setattr("ofti.ui_curses.viewer.Viewer.display", lambda *_: None)
    pipeline.pipeline_editor_screen(FakeScreen(keys=[ord("h")]), case_dir)

    (case_dir / "system").mkdir()
    (case_dir / "system" / "topoSetDict").write_text("actions();\n")
    monkeypatch.setattr("ofti.ui_curses.menus.Menu.navigate", lambda *_: 0)
    monkeypatch.setattr("ofti.tools.postprocessing.run_tool_command", lambda *_a, **_k: None)
    postprocessing.sampling_sets_screen(FakeScreen(), case_dir)


def test_parametric_presets_screen(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    presets = case_dir / "ofti.parametric"
    presets.write_text("demo | system/controlDict | application | simpleFoam\n")
    monkeypatch.setattr("ofti.tools.postprocessing.build_parametric_cases", lambda *_a, **_k: [case_dir])
    monkeypatch.setattr("ofti.tools.postprocessing.run_cases", lambda *_a, **_k: [])
    monkeypatch.setattr("ofti.ui_curses.menus.Menu.navigate", lambda *_: 0)
    monkeypatch.setattr("ofti.tools.postprocessing.prompt_line", lambda *_: "n")
    monkeypatch.setattr("ofti.ui_curses.viewer.Viewer.display", lambda *_: None)
    postprocessing.parametric_presets_screen(FakeScreen(), case_dir)


@pytest.mark.skipif(
    not foamlib_integration.available(),
    reason="foamlib required for parametric study screen",
)
def test_parametric_study_screen(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    monkeypatch.setattr("ofti.tools.parametric.build_parametric_cases", lambda *_a, **_k: [case_dir])
    monkeypatch.setattr("ofti.tools.parametric.run_cases", lambda *_a, **_k: [])
    monkeypatch.setattr("ofti.tools.parametric.prompt_line", lambda *_: "application")
    monkeypatch.setattr("ofti.ui_curses.viewer.Viewer.display", lambda *_: None)
    monkeypatch.setattr("ofti.ui_curses.menus.fzf_enabled", lambda: False)
    from ofti.tools.parametric import foamlib_parametric_study_screen
    screen = FakeScreen(inputs=["system/controlDict", "application", "simpleFoam", "n"])
    foamlib_parametric_study_screen(screen, case_dir)


def test_reconstruct_and_parallel_screens(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "processor0").mkdir()
    monkeypatch.setattr("ofti.tools.reconstruct._run_simple_tool", lambda *_: None)
    monkeypatch.setattr("ofti.ui_curses.menus.Menu.navigate", lambda *_: 0)
    reconstruct.reconstruct_manager_screen(FakeScreen(), case_dir)

    monkeypatch.setattr("ofti.tools.reconstruct.run_trusted", lambda *_a, **_k: types.SimpleNamespace(returncode=0, stdout="", stderr=""))
    ok, _ = reconstruct.reconstruct_latest_once(case_dir)
    assert ok

    run.parallel_consistency_screen(FakeScreen(), case_dir)


def test_job_status_poll_screen(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    from ofti.tools.shell_tools import job_status_poll_screen

    job_status_poll_screen(FakeScreen(keys=[ord("h")]), case_dir)

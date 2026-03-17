from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.app.menu_utils import menu_choice
from ofti.app.menus.case_tools import (
    adopt_untracked_screen,
    run_convergence_check_screen,
    run_stability_check_screen,
    show_case_status_screen,
    show_current_jobs_screen,
    show_eta_forecast_screen,
    show_runtime_criteria_screen,
    show_runtime_report_screen,
)
from ofti.app.state import AppState, Screen
from ofti.foamlib.parametric import preprocessing_available
from ofti.tools.job_control import pause_job_screen, resume_job_screen, stop_job_screen
from ofti.tools.parametric import foamlib_parametric_study_screen
from ofti.tools.pipeline import pipeline_editor_screen, pipeline_runner_screen
from ofti.tools.solver import (
    run_current_solver_live,
    run_current_solver_live_custom_log,
    run_current_solver_parallel,
    solver_job_running,
    solver_status_line,
)
from ofti.tools.solver_control import safe_stop_screen, solver_resurrection_screen
from ofti.ui_curses.help import simulation_help


def simulation_menu(
    stdscr: Any,
    case_path: Path,
    state: AppState,
    *,
    command_handler: Any | None = None,
    command_suggestions: Any | None = None,
) -> Screen:
    options = [
        "Edit case pipeline",
        "Run case pipeline",
        "Run solver",
        "Run solver (custom log)",
        "Run solver parallel",
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
        "Safe stop",
        "Resume solver",
        "Parametric wizard",
        "Back",
    ]
    disabled: set[int] = set()
    disabled_reasons: dict[int, str] = {}
    disabled_helpers: dict[int, str] = {}
    control_dict = case_path / "system" / "controlDict"
    decompose_dict = case_path / "system" / "decomposeParDict"
    if not control_dict.is_file():
        for idx in (2, 3, 16, 17):
            disabled.add(idx)
            disabled_reasons[idx] = (
                "Simulation requires system/controlDict; create a sample config in Config Manager."
            )
            disabled_helpers[idx] = "config"
    if not decompose_dict.is_file():
        disabled.add(4)
        disabled_reasons[4] = (
            "Parallel run requires system/decomposeParDict; create it in Config Manager."
        )
        disabled_helpers[4] = "config"
    if state.no_foam:
        no_foam_sensitive = (0, 1, 2, 3, 4, 16, 17, 18)
        disabled.update(no_foam_sensitive)
        for idx in no_foam_sensitive:
            disabled_reasons.setdefault(
                idx,
                "OpenFOAM environment not initialized; run :foamenv to enable simulation features.",
            )
    if not preprocessing_available():
        disabled.add(18)
        disabled_reasons.setdefault(
            18,
            "Parametric wizard requires foamlib preprocessing extras.",
        )
    solver_running = solver_job_running(case_path)
    status_line = solver_status_line(case_path)
    if solver_running:
        status_line = "Solver running (see logs)"
    while True:
        choice = menu_choice(
            stdscr,
            "Simulation",
            options,
            state,
            "menu:sim",
            command_handler=command_handler,
            command_suggestions=command_suggestions,
            disabled_indices=disabled,
            disabled_reasons=disabled_reasons,
            disabled_helpers=disabled_helpers,
            help_lines=simulation_help(),
            status_line=status_line,
        )
        if choice in (-1, len(options) - 1):
            return Screen.MAIN_MENU
        if choice == 0:
            pipeline_editor_screen(stdscr, case_path)
        elif choice == 1:
            pipeline_runner_screen(stdscr, case_path)
        elif choice == 2:
            run_current_solver_live(stdscr, case_path)
        elif choice == 3:
            run_current_solver_live_custom_log(stdscr, case_path)
        elif choice == 4:
            run_current_solver_parallel(stdscr, case_path)
        elif choice == 5:
            show_case_status_screen(stdscr, case_path)
        elif choice == 6:
            show_current_jobs_screen(stdscr, case_path, live=True)
        elif choice == 7:
            show_runtime_criteria_screen(stdscr, case_path)
        elif choice == 8:
            show_eta_forecast_screen(stdscr, case_path)
        elif choice == 9:
            show_runtime_report_screen(stdscr, case_path)
        elif choice == 10:
            run_convergence_check_screen(stdscr, case_path)
        elif choice == 11:
            run_stability_check_screen(stdscr, case_path)
        elif choice == 12:
            adopt_untracked_screen(stdscr, case_path)
        elif choice == 13:
            stop_job_screen(stdscr, case_path)
        elif choice == 14:
            pause_job_screen(stdscr, case_path)
        elif choice == 15:
            resume_job_screen(stdscr, case_path)
        elif choice == 16:
            safe_stop_screen(stdscr, case_path)
        elif choice == 17:
            solver_resurrection_screen(stdscr, case_path)
        elif choice == 18:
            foamlib_parametric_study_screen(stdscr, case_path)

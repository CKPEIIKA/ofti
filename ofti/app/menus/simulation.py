from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.app.menu_utils import menu_choice
from ofti.app.state import AppState, Screen
from ofti.tools.parametric import foamlib_parametric_study_screen
from ofti.tools.pipeline import pipeline_editor_screen, pipeline_runner_screen
from ofti.tools.solver import (
    run_current_solver_live,
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
        "Run solver parallel",
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
        for idx in (2, 4, 5):
            disabled.add(idx)
            disabled_reasons[idx] = (
                "Simulation requires system/controlDict; create a sample config in Config Manager."
            )
            disabled_helpers[idx] = "config"
    if not decompose_dict.is_file():
        disabled.add(3)
        disabled_reasons[3] = (
            "Parallel run requires system/decomposeParDict; create it in Config Manager."
        )
        disabled_helpers[3] = "config"
    if state.no_foam:
        disabled.update(range(len(options) - 1))
        for idx in range(len(options) - 1):
            disabled_reasons.setdefault(
                idx,
                "OpenFOAM environment not initialized; run :foamenv to enable simulation features.",
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
            run_current_solver_parallel(stdscr, case_path)
        elif choice == 4:
            safe_stop_screen(stdscr, case_path)
        elif choice == 5:
            solver_resurrection_screen(stdscr, case_path)
        elif choice == 6:
            foamlib_parametric_study_screen(stdscr, case_path)

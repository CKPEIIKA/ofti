from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.app.menu_utils import has_processor_dirs, menu_choice
from ofti.app.state import AppState, Screen
from ofti.tools.case_ops import open_paraview_screen
from ofti.tools.logs_analysis import residual_timeline_screen
from ofti.tools.logs_fields import field_summary_screen
from ofti.tools.logs_probes import probes_viewer_screen
from ofti.tools.logs_view import logs_screen
from ofti.tools.postprocessing import postprocessing_browser_screen, sampling_sets_screen
from ofti.tools.reconstruct import reconstruct_manager_screen
from ofti.tools.shell_tools import run_shell_script_screen
from ofti.tools.tool_dicts_foamcalc import foam_calc_prompt
from ofti.ui_curses.help import postprocessing_help


def postprocessing_menu(
    stdscr: Any,
    case_path: Path,
    state: AppState,
    *,
    command_handler: Any | None = None,
    command_suggestions: Any | None = None,
) -> Screen:
    options = [
        "Reconstruct manager",
        "View logs",
        "Open ParaView",
        "Residual timeline",
        "PostProcessing browser",
        "Field summary",
        "Sampling & sets",
        "Probes viewer",
        "foamCalc",
        "Run shell script",
        "Back",
    ]
    disabled = set(range(len(options) - 1)) if state.no_foam else set()
    disabled_reasons: dict[int, str] = {}
    disabled_helpers: dict[int, str] = {}
    if state.no_foam:
        for idx in range(len(options) - 1):
            disabled_reasons[idx] = (
                "OpenFOAM environment not initialized; run :foamenv to enable simulation features."
            )
    if not has_processor_dirs(case_path):
        disabled.add(0)
        disabled_reasons.setdefault(
            0, "Post-processing requires processor* directories (decomposePar first).",
        )
        disabled_helpers[0] = "diagnostics"
    foamcalc_dict = case_path / "system" / "foamCalcDict"
    if not foamcalc_dict.is_file():
        disabled.add(8)
        disabled_reasons[8] = (
            "foamCalc requires system/foamCalcDict; create it via Config Manager."
        )
        disabled_helpers[8] = "config"
    while True:
        choice = menu_choice(
            stdscr,
            "Post-Processing",
            options,
            state,
            "menu:post",
            command_handler=command_handler,
            command_suggestions=command_suggestions,
            disabled_indices=disabled,
            help_lines=postprocessing_help(),
        )
        if choice in (-1, len(options) - 1):
            return Screen.MAIN_MENU
        if choice == 0:
            reconstruct_manager_screen(stdscr, case_path)
        elif choice == 1:
            logs_screen(stdscr, case_path)
        elif choice == 2:
            open_paraview_screen(stdscr, case_path)
        elif choice == 3:
            residual_timeline_screen(stdscr, case_path)
        elif choice == 4:
            postprocessing_browser_screen(stdscr, case_path)
        elif choice == 5:
            field_summary_screen(stdscr, case_path)
        elif choice == 6:
            sampling_sets_screen(stdscr, case_path)
        elif choice == 7:
            probes_viewer_screen(stdscr, case_path)
        elif choice == 8:
            foam_calc_prompt(stdscr, case_path)
        elif choice == 9:
            run_shell_script_screen(stdscr, case_path)

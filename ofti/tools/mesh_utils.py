from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.tools.input_prompts import prompt_args_line, prompt_line
from ofti.tools.menu_helpers import build_menu
from ofti.tools.runner import _show_message, run_tool_command
from ofti.ui_curses.viewer import Viewer


def renumber_mesh_screen(stdscr: Any, case_path: Path) -> None:
    run_tool_command(
        stdscr,
        case_path,
        "renumberMesh",
        ["renumberMesh"],
        status="Running renumberMesh...",
    )


def transform_points_screen(stdscr: Any, case_path: Path) -> None:
    options = ["Translate", "Rotate", "Scale", "Custom args", "Back"]
    menu = build_menu(
        stdscr,
        "transformPoints",
        options,
        menu_key="menu:transform_points",
    )
    choice = menu.navigate()
    if choice in (-1, len(options) - 1):
        return
    mode = options[choice].lower()
    cmd = ["transformPoints"]
    if mode == "custom args":
        args = prompt_args_line(stdscr, "transformPoints args: ")
        if args is None:
            return
        cmd += args
    else:
        value = prompt_line(stdscr, f"{mode} vector (e.g. (1 0 0)): ")
        if not value:
            return
        flag = f"-{mode}"
        cmd += [flag, value.strip()]
    run_tool_command(
        stdscr,
        case_path,
        "transformPoints",
        cmd,
        status=f"Running {' '.join(cmd)}...",
    )


def cfmesh_screen(stdscr: Any, case_path: Path) -> None:
    cfmesh_dict = case_path / "system" / "cfMeshDict"
    if not cfmesh_dict.is_file():
        _show_message(stdscr, "system/cfMeshDict not found.")
        return
    options = ["Run cartesianMesh", "View cartesianMesh log", "Back"]
    menu = build_menu(
        stdscr,
        "cfMesh",
        options,
        menu_key="menu:cfmesh",
    )
    choice = menu.navigate()
    if choice in (-1, len(options) - 1):
        return
    if choice == 0:
        run_tool_command(
            stdscr,
            case_path,
            "cartesianMesh",
            ["cartesianMesh"],
            status="Running cartesianMesh...",
        )
        return
    if choice == 1:
        log_path = case_path / "log.cartesianMesh"
        if not log_path.is_file():
            _show_message(stdscr, "log.cartesianMesh not found.")
            return
        Viewer(stdscr, log_path.read_text(errors="ignore")).display()

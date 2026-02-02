from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from ofti.core.tool_output import CommandResult, format_command_result
from ofti.foam.subprocess_utils import run_trusted
from ofti.tools.runner import (
    _record_tool_status,
    _show_message,
    _with_no_foam_hint,
    _write_tool_log,
)
from ofti.ui_curses.inputs import prompt_input
from ofti.ui_curses.layout import status_message
from ofti.ui_curses.menus import Menu
from ofti.ui_curses.viewer import Viewer


def renumber_mesh_screen(stdscr: Any, case_path: Path) -> None:
    status_message(stdscr, "Running renumberMesh...")
    cmd = ["renumberMesh"]
    _run_and_show(stdscr, case_path, "renumberMesh", cmd)


def transform_points_screen(stdscr: Any, case_path: Path) -> None:
    options = ["Translate", "Rotate", "Scale", "Custom args", "Back"]
    menu = Menu(stdscr, "transformPoints", options)
    choice = menu.navigate()
    if choice in (-1, len(options) - 1):
        return
    mode = options[choice].lower()
    cmd = ["transformPoints"]
    if mode == "custom args":
        args = prompt_input(stdscr, "transformPoints args: ")
        if args is None:
            return
        cmd += shlex.split(args)
    else:
        value = prompt_input(stdscr, f"{mode} vector (e.g. (1 0 0)): ")
        if not value:
            return
        flag = f"-{mode}"
        cmd += [flag, value.strip()]
    status_message(stdscr, f"Running {' '.join(cmd)}...")
    _run_and_show(stdscr, case_path, "transformPoints", cmd)


def cfmesh_screen(stdscr: Any, case_path: Path) -> None:
    cfmesh_dict = case_path / "system" / "cfMeshDict"
    if not cfmesh_dict.is_file():
        _show_message(stdscr, "system/cfMeshDict not found.")
        return
    options = ["Run cartesianMesh", "View cartesianMesh log", "Back"]
    menu = Menu(stdscr, "cfMesh", options)
    choice = menu.navigate()
    if choice in (-1, len(options) - 1):
        return
    if choice == 0:
        status_message(stdscr, "Running cartesianMesh...")
        _run_and_show(stdscr, case_path, "cartesianMesh", ["cartesianMesh"])
        return
    if choice == 1:
        log_path = case_path / "log.cartesianMesh"
        if not log_path.is_file():
            _show_message(stdscr, "log.cartesianMesh not found.")
            return
        Viewer(stdscr, log_path.read_text(errors="ignore")).display()


def _run_and_show(
    stdscr: Any,
    case_path: Path,
    name: str,
    cmd: list[str],
) -> None:
    try:
        result = run_trusted(
            cmd,
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run {name}: {exc}"))
        return
    _write_tool_log(case_path, name, result.stdout, result.stderr)
    _record_tool_status(name, f"exit {result.returncode}")
    summary = format_command_result(
        [f"$ cd {case_path}", f"$ {' '.join(cmd)}"],
        CommandResult(result.returncode, result.stdout, result.stderr),
    )
    Viewer(stdscr, summary).display()

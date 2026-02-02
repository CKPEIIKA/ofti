from __future__ import annotations

import curses
import shutil
from pathlib import Path
from typing import Any

from ofti.foam.subprocess_utils import run_trusted
from ofti.tools.input_prompts import prompt_line
from ofti.tools.runner import _show_message
from ofti.ui_curses.viewer import Viewer


def open_paraview_screen(stdscr: Any, case_path: Path) -> None:
    foam_file = case_path / f"{case_path.name}.foam"
    try:
        foam_file.write_text("")
    except OSError as exc:
        _show_message(stdscr, f"Failed to create {foam_file.name}: {exc}")
        return

    resolved = shutil.which("paraview")
    if not resolved:
        _show_message(
            stdscr,
            f"Created {foam_file.name}. paraview not found on PATH.",
        )
        return
    curses.endwin()
    try:
        run_trusted([resolved, str(foam_file)], capture_output=False, check=False)
    finally:
        stdscr.clear()
        stdscr.refresh()


def clone_case(stdscr: Any, case_path: Path, name: str | None = None) -> None:
    if not name:
        stdscr.clear()
        name = prompt_line(stdscr, "New case name (folder): ")
        if name is None:
            return
        if not name:
            return
    dest = Path(name)
    if not dest.is_absolute():
        dest = case_path.parent / dest
    if dest.exists():
        _show_message(stdscr, f"Destination already exists: {dest}")
        return
    try:
        shutil.copytree(case_path, dest, symlinks=True)
    except OSError as exc:
        _show_message(stdscr, f"Failed to clone case: {exc}")
        return
    _clean_clone(dest)
    Viewer(stdscr, f"Cloned case to {dest}").display()


def _clean_clone(case_path: Path) -> None:  # noqa: C901
    for path in case_path.glob("log.*"):
        try:
            path.unlink()
        except OSError:
            continue
    for entry in case_path.iterdir():
        if entry.is_dir() and entry.name.startswith("processor"):
            shutil.rmtree(entry, ignore_errors=True)
    for entry in case_path.iterdir():
        if not entry.is_dir():
            continue
        try:
            value = float(entry.name)
        except ValueError:
            continue
        if value >= 0:
            shutil.rmtree(entry, ignore_errors=True)
    post = case_path / "postProcessing"
    if post.exists():
        shutil.rmtree(post, ignore_errors=True)
    mesh = case_path / "constant" / "polyMesh"
    if mesh.exists():
        shutil.rmtree(mesh, ignore_errors=True)

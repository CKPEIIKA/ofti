from __future__ import annotations

import curses
import os
from pathlib import Path
from typing import Any

from ofti.foam.config import get_config, key_in
from ofti.foam.exceptions import QuitAppError
from ofti.foam.openfoam_env import (
    auto_detect_bashrc_paths,
    resolve_openfoam_bashrc,
    wm_project_dir_from_bashrc,
)
from ofti.ui_curses.help import menu_hint
from ofti.ui_curses.menus import Menu


def _show_message(stdscr: Any, message: str) -> None:
    stdscr.clear()
    stdscr.addstr(message + "\n")
    stdscr.addstr("Press any key to continue.\n")
    stdscr.refresh()
    key = stdscr.getch()
    if key_in(key, get_config().keys.get("quit", [])):
        raise QuitAppError()


def _prompt_text(stdscr: Any, prompt: str) -> str:  # noqa: C901
    height, width = stdscr.getmaxyx()
    buffer: list[str] = []
    cursor = 0

    def render() -> None:
        try:
            stdscr.move(height - 1, 0)
            stdscr.clrtoeol()
            display = f"{prompt}{''.join(buffer)}"
            stdscr.addstr(height - 1, 0, display[: max(1, width - 1)])
            stdscr.move(height - 1, min(width - 1, len(prompt) + cursor))
            stdscr.refresh()
        except curses.error:
            pass

    render()
    while True:
        key = stdscr.getch()
        if key in (curses.KEY_ENTER, 10, 13):
            return "".join(buffer).strip()
        if key in (27,):  # ESC
            return ""
        if key in (curses.KEY_BACKSPACE, 127, 8):
            if cursor > 0:
                buffer.pop(cursor - 1)
                cursor -= 1
            render()
            continue
        if key == curses.KEY_LEFT:
            if cursor > 0:
                cursor -= 1
            render()
            continue
        if key == curses.KEY_RIGHT:
            if cursor < len(buffer):
                cursor += 1
            render()
            continue
        if 32 <= key <= 126:
            buffer.insert(cursor, chr(key))
            cursor += 1
            render()


def _set_openfoam_bashrc(path: Path | None) -> None:
    cfg = get_config()
    if path is None:
        cfg.openfoam_bashrc = None
        os.environ.pop("OFTI_BASHRC", None)
        return
    cfg.openfoam_bashrc = str(path)
    os.environ["OFTI_BASHRC"] = str(path)
    wm_dir = wm_project_dir_from_bashrc(path)
    if wm_dir:
        os.environ["WM_PROJECT_DIR"] = wm_dir


def openfoam_env_screen(stdscr: Any) -> None:
    """
    Select an OpenFOAM bashrc for the current session.
    """
    current = resolve_openfoam_bashrc()
    candidates = auto_detect_bashrc_paths()
    if current and current not in candidates:
        candidates.insert(0, current)

    labels = []
    for path in candidates:
        suffix = " (current)" if current and path == current else ""
        labels.append(f"{path}{suffix}")

    manual_index = len(labels)
    clear_index = manual_index + 1
    back_index = clear_index + 1
    tail_labels = ["Enter path manually", "Clear selection", "Back"]
    menu = Menu(
        stdscr,
        "Select OpenFOAM bashrc",
        [*labels, *tail_labels],
        hint_provider=lambda idx: (
            "Use selected bashrc."
            if 0 <= idx < len(labels)
            else menu_hint("menu:openfoam_env", tail_labels[idx - len(labels)])
            if 0 <= idx - len(labels) < len(tail_labels)
            else ""
        ),
    )
    choice = menu.navigate()
    if choice in (-1, back_index):
        return
    if choice == manual_index:
        manual = _prompt_text(stdscr, "bashrc path: ")
        if not manual:
            return
        path = Path(manual).expanduser()
        if not path.is_file():
            _show_message(stdscr, f"Path not found: {path}")
            return
        _set_openfoam_bashrc(path)
        _show_message(stdscr, f"Using OpenFOAM bashrc: {path}")
        return
    if choice == clear_index:
        _set_openfoam_bashrc(None)
        _show_message(stdscr, "Cleared OFTI_BASHRC for this session.")
        return

    selected = candidates[choice]
    _set_openfoam_bashrc(selected)
    _show_message(stdscr, f"Using OpenFOAM bashrc: {selected}")

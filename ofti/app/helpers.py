from __future__ import annotations

import curses
import os
from pathlib import Path
from typing import Any

from ofti.foam.config import get_config, key_hint, key_in
from ofti.foam.exceptions import QuitAppError


def option_index(options: list[str], selection: str | None) -> int:
    if not selection:
        return 0
    try:
        return options.index(selection)
    except ValueError:
        return 0


def show_message(stdscr: Any, message: str) -> None:
    stdscr.clear()
    stdscr.addstr(message + "\n")
    stdscr.addstr("Press any key to continue.\n")
    stdscr.refresh()
    key = stdscr.getch()
    if key_in(key, get_config().keys.get("quit", [])):
        raise QuitAppError()


def is_case_dir(path: Path) -> bool:
    return (path / "system" / "controlDict").is_file()


def list_dir_entries(path: Path) -> tuple[list[Path], list[Path]]:
    dirs: list[Path] = []
    files: list[Path] = []
    try:
        for entry in os.scandir(path):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                dirs.append(Path(entry.path))
            elif entry.is_file():
                files.append(Path(entry.path))
    except OSError:
        return [], []
    return sorted(dirs), sorted(files)


def select_case_directory(stdscr: Any, start_path: Path) -> Path | None:  # noqa: C901, PLR0912
    current = start_path if start_path.is_dir() else start_path.parent
    index = 0
    scroll = 0
    cfg = get_config()

    while True:
        dirs, files = list_dir_entries(current)
        entries: list[tuple[str, Path | None]] = [
            ("[Use this folder]", None),
            ("..", current.parent if current.parent != current else None),
        ]
        entries += [(f"{path.name}/", path) for path in dirs]
        entries += [(path.name, path) for path in files]

        labels = [label for label, _path in entries]
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        header = f"Select case folder: {current}"
        back_hint = key_hint("back", "h")
        hint = f"Enter: open/select  e: use this folder  {back_hint}: back"
        try:
            stdscr.addstr(0, 0, header[: max(1, width - 1)])
            stdscr.addstr(1, 0, hint[: max(1, width - 1)])
        except curses.error:
            pass

        scroll = menu_scroll(index, scroll, stdscr, len(labels), header_rows=3)
        visible = max(0, height - 3)
        for row_idx, label_idx in enumerate(range(scroll, min(len(labels), scroll + visible))):
            prefix = ">> " if label_idx == index else "   "
            line = f"{prefix}{labels[label_idx]}"
            try:
                if label_idx == index:
                    stdscr.attron(curses.color_pair(1))
                stdscr.addstr(3 + row_idx, 0, line[: max(1, width - 1)])
                if label_idx == index:
                    stdscr.attroff(curses.color_pair(1))
            except curses.error:
                break

        stdscr.refresh()
        key = stdscr.getch()

        if key_in(key, cfg.keys.get("quit", [])):
            raise QuitAppError()
        if key in (curses.KEY_UP,) or key_in(key, cfg.keys.get("up", [])):
            index = (index - 1) % len(labels)
            continue
        if key in (curses.KEY_DOWN,) or key_in(key, cfg.keys.get("down", [])):
            index = (index + 1) % len(labels)
            continue
        if key_in(key, cfg.keys.get("top", [])):
            index = 0
            continue
        if key_in(key, cfg.keys.get("bottom", [])):
            index = len(labels) - 1
            continue
        if key_in(key, cfg.keys.get("back", [])):
            if current.parent != current:
                current = current.parent
                index = 0
                scroll = 0
            continue
        if key == ord("e"):
            if is_case_dir(current):
                return current
            show_message(stdscr, "Not an OpenFOAM case (missing system/controlDict).")
            continue
        if key in (curses.KEY_ENTER, 10, 13) or key_in(key, cfg.keys.get("select", [])):
            label, path = entries[index]
            if label == "[Use this folder]":
                if is_case_dir(current):
                    return current
                show_message(stdscr, "Not an OpenFOAM case (missing system/controlDict).")
                continue
            if label == ".." and path is not None:
                current = path
                index = 0
                scroll = 0
                continue
            if path is None:
                continue
            if path.is_dir():
                current = path
                index = 0
                scroll = 0
                continue
            show_message(stdscr, f"{path.name} is not a folder.")


def prompt_command(stdscr: Any, suggestions: list[str] | None) -> str:  # noqa: C901, PLR0912
    height, width = stdscr.getmaxyx()
    buffer: list[str] = []
    cursor = 0
    last_matches: list[str] = []
    match_index = 0
    last_buffer = ""

    def render() -> None:
        try:
            stdscr.move(height - 1, 0)
            stdscr.clrtoeol()
            display = ":" + "".join(buffer)
            stdscr.addstr(height - 1, 0, display[: max(1, width - 1)])
            stdscr.move(height - 1, min(width - 1, 1 + cursor))
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
        if key == 9:  # TAB
            pool = suggestions or []
            current = "".join(buffer)
            if current != last_buffer:
                last_matches = [s for s in pool if s.startswith(current)]
                match_index = 0
                last_buffer = current
            if last_matches:
                completion = last_matches[match_index % len(last_matches)]
                buffer = list(completion)
                cursor = len(buffer)
                match_index += 1
                render()
            continue
        if 32 <= key <= 126:
            buffer.insert(cursor, chr(key))
            cursor += 1
            render()


def menu_scroll(
    current: int, scroll: int, stdscr: Any, total: int, header_rows: int,
) -> int:
    height, _ = stdscr.getmaxyx()
    visible = max(0, height - header_rows - 1)
    if visible <= 0:
        return 0
    if current < scroll:
        scroll = current
    elif current >= scroll + visible:
        scroll = current - visible + 1
    max_scroll = max(0, total - visible)
    return min(scroll, max_scroll)


def set_no_foam_mode(state: Any, enabled: bool, reason: str | None = None) -> None:
    state.no_foam = enabled
    state.no_foam_reason = reason
    if enabled:
        os.environ["OFTI_NO_FOAM"] = "1"
    else:
        os.environ.pop("OFTI_NO_FOAM", None)

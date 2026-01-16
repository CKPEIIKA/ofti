from __future__ import annotations

import curses
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
import threading
from pathlib import Path
from typing import List, Any, Optional

from .browser import BrowserCallbacks, entry_browser_screen
from .editor import Entry, EntryEditor, Viewer, autoformat_value
from .entry_meta import choose_validator
from .layout import (
    case_banner_lines,
    case_overview_lines,
    draw_status_bar,
    next_spinner,
    status_message,
)
from .domain import DictionaryFile, EntryRef, Case
from .menus import Menu, RootMenu, Submenu
from .commands import CommandCallbacks, command_suggestions, handle_command
from .config import get_config, key_in, fzf_enabled
from .tools import (
    tools_screen,
    diagnostics_screen,
    run_current_solver,
)
from .openfoam import (
    FileCheckResult,
    OpenFOAMError,
    discover_case_files,
    ensure_environment,
    list_keywords,
    list_subkeys,
    read_entry,
    verify_case,
    write_entry,
)


class Screen(Enum):
    MAIN_MENU = "main_menu"
    EDITOR = "editor"
    ENTRY_BROWSER = "entry_browser"
    CHECK = "check"
    TOOLS = "tools"
    DIAGNOSTICS = "diagnostics"
    SEARCH = "search"
    VIEWER = "viewer"
    NO_FOAM_FILE = "no_foam_file"


@dataclass
class AppState:
    no_foam: bool = False
    current_screen: Screen = Screen.MAIN_MENU
    last_action: Optional[str] = None
    check_lock: threading.Lock = field(default_factory=threading.Lock)
    check_in_progress: bool = False
    check_total: int = 0
    check_done: int = 0
    check_current: Optional[Path] = None
    check_results: Optional[dict[Path, FileCheckResult]] = None
    check_thread: Optional[threading.Thread] = None

    def transition(self, screen: Screen, action: Optional[str] = None) -> None:
        self.current_screen = screen
        if action is not None:
            self.last_action = action

    def check_status_line(self) -> str:
        with self.check_lock:
            if self.check_in_progress:
                current = f" {self.check_current.name}" if self.check_current else ""
                return f"{next_spinner()} check: {self.check_done}/{self.check_total}{current}"
        return ""


def run_tui(case_dir: str, debug: bool = False, no_foam: bool = False) -> None:
    """
    Run the TUI on the given OpenFOAM case directory.
    """
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    # Always resolve the case path so that any paths
    # discovered later share the same root, which keeps
    # Path.relative_to calls safe.
    case_path = Path(case_dir).resolve()
    state = AppState(no_foam=no_foam)
    if no_foam:
        os.environ["OF_TUI_NO_FOAM"] = "1"
    else:
        os.environ.pop("OF_TUI_NO_FOAM", None)
    curses.wrapper(_main, case_path, debug, state)


def _main(stdscr: Any, case_path: Path, debug: bool, state: AppState) -> None:
    curses.start_color()
    cfg = get_config()
    fg = _color_from_name(cfg.colors.get("focus_fg", "black"), curses.COLOR_BLACK)
    bg = _color_from_name(cfg.colors.get("focus_bg", "cyan"), curses.COLOR_CYAN)
    curses.init_pair(1, fg, bg)

    if not state.no_foam:
        try:
            ensure_environment()
        except OpenFOAMError as exc:
            stdscr.clear()
            stdscr.addstr(str(exc) + "\n")
            stdscr.addstr("Press any key to exit.\n")
            stdscr.refresh()
            stdscr.getch()
            return

    try:
        _main_loop(stdscr, case_path, state)
    except KeyboardInterrupt:
        # Clean, user-initiated exit with restored terminal state.
        return
    except (OpenFOAMError, OSError, RuntimeError, ValueError) as exc:  # pragma: no cover
        if debug:
            # Re-raise to get a full traceback in debug mode.
            raise
        _show_message(stdscr, f"Unexpected error: {exc}")


def _main_loop(stdscr: Any, case_path: Path, state: AppState) -> None:
    foam_case = Case(root=case_path)
    sections = discover_case_files(foam_case.root)
    section_names = [name for name, files in sections.items() if files]
    if not section_names:
        stdscr.addstr("No OpenFOAM case files found.\n")
        stdscr.addstr("Press any key to exit.\n")
        stdscr.refresh()
        stdscr.getch()
        return

    next_screen: Optional[Screen] = Screen.MAIN_MENU
    while next_screen is not None:
        if next_screen == Screen.MAIN_MENU:
            next_screen = _main_menu_screen(stdscr, case_path, state)
            continue
        if next_screen == Screen.CHECK:
            state.transition(Screen.CHECK, action="check")
            _check_syntax_screen(stdscr, case_path, state)
            next_screen = Screen.MAIN_MENU
            continue
        if next_screen == Screen.TOOLS:
            state.transition(Screen.TOOLS, action="tools")
            tools_screen(stdscr, case_path)
            next_screen = Screen.MAIN_MENU
            continue
        if next_screen == Screen.DIAGNOSTICS:
            state.transition(Screen.DIAGNOSTICS, action="diagnostics")
            diagnostics_screen(stdscr, case_path)
            next_screen = Screen.MAIN_MENU
            continue
        if next_screen == Screen.SEARCH:
            state.transition(Screen.SEARCH, action="search")
            _global_search_screen(stdscr, case_path, state)
            next_screen = Screen.MAIN_MENU
            continue
        if next_screen == Screen.EDITOR:
            state.transition(Screen.EDITOR, action="editor")
            _editor_screen(stdscr, case_path, state)
            next_screen = Screen.MAIN_MENU
            continue
        next_screen = Screen.MAIN_MENU


def _main_menu_screen(
    stdscr: Any, case_path: Path, state: AppState
) -> Optional[Screen]:
    state.transition(Screen.MAIN_MENU)
    has_fzf = fzf_enabled()

    menu_options = [
        "Editor",
        "Check syntax",
        "Tools",
        "Diagnostics",
    ]
    check_index = 1
    tools_index = 2
    diag_index = 3

    search_index: Optional[int] = None
    if has_fzf:
        search_index = len(menu_options)
        menu_options.append("Global search")

    quit_index = len(menu_options)
    menu_options.append("Quit")

    case_meta = _case_metadata(case_path)
    banner_lines = case_banner_lines(case_meta)
    overview_lines = case_overview_lines(case_meta)
    callbacks = _command_callbacks()
    root_menu = RootMenu(
        stdscr,
        "Main menu",
        menu_options,
        extra_lines=overview_lines,
        banner_lines=banner_lines,
        command_handler=lambda cmd: handle_command(stdscr, case_path, state, cmd, callbacks),
        command_suggestions=lambda: command_suggestions(case_path),
    )
    choice = root_menu.navigate()
    if choice == -1 or choice == quit_index:
        return None
    if choice == check_index:
        return Screen.CHECK
    if choice == tools_index:
        return Screen.TOOLS
    if choice == diag_index:
        return Screen.DIAGNOSTICS
    if search_index is not None and choice == search_index:
        return Screen.SEARCH
    return Screen.EDITOR


def _select_case_file(
    stdscr: Any,
    case_path: Path,
    state: AppState,
    sections: dict[str, list[Path]],
) -> Optional[Path]:
    section_names = [name for name, files in sections.items() if files]
    if not section_names:
        _show_message(stdscr, "No OpenFOAM case files found in this case.")
        return None

    while True:
        callbacks = _command_callbacks()
        section_menu = Menu(
            stdscr,
            "Editor – select section",
            section_names + ["Back"],
            command_handler=lambda cmd: handle_command(stdscr, case_path, state, cmd, callbacks),
            command_suggestions=lambda: command_suggestions(case_path),
        )
        section_index = section_menu.navigate()
        if section_index == -1 or section_index == len(section_names):
            return None

        section = section_names[section_index]
        files = sections.get(section, [])
        if not files:
            _show_message(stdscr, f"No files found in section {section}.")
            continue

        file_labels = [f.relative_to(case_path).as_posix() for f in files]
        while True:
            callbacks = _command_callbacks()
            file_menu = Menu(
                stdscr,
                f"{section} files",
                file_labels + ["Back"],
                command_handler=lambda cmd: handle_command(stdscr, case_path, state, cmd, callbacks),
                command_suggestions=lambda: command_suggestions(case_path),
            )
            file_index = file_menu.navigate()
            if file_index == -1 or file_index == len(file_labels):
                break
            return files[file_index]


def _editor_screen(stdscr: Any, case_path: Path, state: AppState) -> None:
    sections = discover_case_files(case_path)
    while True:
        state.transition(Screen.EDITOR)
        file_path = _select_case_file(stdscr, case_path, state, sections)
        if file_path is None:
            return
        if state.no_foam:
            state.transition(Screen.NO_FOAM_FILE, action="no_foam_file")
            _no_foam_file_screen(stdscr, case_path, file_path, state)
        else:
            state.transition(Screen.ENTRY_BROWSER, action="entry_browser")
            callbacks = _browser_callbacks(case_path, state)
            entry_browser_screen(stdscr, case_path, file_path, state, callbacks)


def _file_screen(stdscr: Any, case_path: Path, file_path: Path, state: AppState) -> None:
    try:
        keywords = list_keywords(file_path)
    except OpenFOAMError as exc:
        stdscr.clear()
        stdscr.addstr(f"Error reading {file_path.relative_to(case_path)}:\n")
        stdscr.addstr(str(exc) + "\n")
        stdscr.addstr("Press any key to go back.\n")
        stdscr.refresh()
        stdscr.getch()
        return

    options = ["Edit entry", "View file", "Back"]
    callbacks = _command_callbacks()
    submenu = Submenu(
        stdscr,
        f"{file_path.relative_to(case_path)}",
        options[:-1],
        command_handler=lambda cmd: handle_command(stdscr, case_path, state, cmd, callbacks),
        command_suggestions=lambda: command_suggestions(case_path),
    )
    while True:
        choice = submenu.navigate()
        if choice == -1 or choice == len(options) - 1:
            return
        if choice == 0:
            _edit_entry_screen(stdscr, case_path, file_path, keywords, state)
        elif choice == 1:
            _view_file_screen(stdscr, file_path)


def _no_foam_file_screen(
    stdscr: Any, case_path: Path, file_path: Path, state: AppState
) -> None:
    options = ["View file", "Open in $EDITOR", "Back"]
    while True:
        callbacks = _command_callbacks()
        menu = Menu(
            stdscr,
            f"{file_path.relative_to(case_path)}",
            options,
            command_handler=lambda cmd: handle_command(stdscr, case_path, state, cmd, callbacks),
            command_suggestions=lambda: command_suggestions(case_path),
        )
        choice = menu.navigate()
        if choice == -1 or choice == len(options) - 1:
            return
        if choice == 0:
            _view_file_screen(stdscr, file_path)
        elif choice == 1:
            _open_file_in_editor(stdscr, file_path)


def _edit_entry_screen(
    stdscr: Any,
    case_path: Path,
    file_path: Path,
    keywords: List[str],
    state: AppState,
    base_entry: Optional[str] = None,
) -> None:
    if not keywords:
        _show_message(stdscr, "No entries found in file.")
        return

    callbacks = _command_callbacks()
    entry_menu = Menu(
        stdscr,
        "Select entry to edit",
        keywords + ["Back"],
        command_handler=lambda cmd: handle_command(stdscr, case_path, state, cmd, callbacks),
        command_suggestions=lambda: command_suggestions(case_path),
    )
    entry_index = entry_menu.navigate()
    if entry_index == -1 or entry_index == len(keywords):
        return

    key = keywords[entry_index]
    full_key = key if base_entry is None else f"{base_entry}.{key}"

    # If this entry has sub-keys, offer to browse deeper.
    subkeys = list_subkeys(file_path, full_key)
    if subkeys:
        # Submenu to choose between browsing sub-entries or editing this entry directly.
        callbacks = _command_callbacks()
        submenu = Menu(
            stdscr,
            f"{full_key} is a dictionary",
            ["Browse sub-entries", "Edit this entry", "Back"],
            command_handler=lambda cmd: handle_command(stdscr, case_path, state, cmd, callbacks),
            command_suggestions=lambda: command_suggestions(case_path),
        )
        choice = submenu.navigate()
        if choice == 0:
            _edit_entry_screen(
                stdscr,
                case_path,
                file_path,
                subkeys,
                state,
                base_entry=full_key,
            )
            return
        if choice in (-1, 2):
            return

    try:
        value = read_entry(file_path, full_key)
    except OpenFOAMError as exc:
        _show_message(stdscr, f"Failed to read entry: {exc}")
        return

    entry = Entry(key=full_key, value=value)
    validator, type_label = choose_validator(full_key, value)

    def on_save(new_value: str) -> bool:
        formatted = autoformat_value(new_value)
        return write_entry(file_path, full_key, formatted)

    editor = EntryEditor(
        stdscr,
        entry,
        on_save,
        validator=validator,
        type_label=type_label,
        subkeys=subkeys,
    )
    editor.edit()


def _view_file_screen(stdscr: Any, file_path: Path) -> None:
    try:
        content = file_path.read_text()
    except OSError as exc:
        _show_message(stdscr, f"Failed to read file: {exc}")
        return

    warnings = _find_suspicious_lines(content)
    if warnings:
        warning_text = "\n".join(["Suspicious lines detected:"] + warnings + ["", content])
    else:
        warning_text = content

    viewer = Viewer(stdscr, warning_text)
    viewer.display()


def _find_suspicious_lines(content: str) -> list[str]:
    warnings: list[str] = []
    brace_depth = 0
    header_done = False
    in_block_comment = False

    lines = content.splitlines()

    def next_significant_line(idx: int) -> Optional[str]:
        for j in range(idx + 1, len(lines)):
            candidate = lines[j].strip()
            if not candidate:
                continue
            if candidate.startswith("//"):
                continue
            if candidate.startswith("/*") or candidate.startswith("*"):
                continue
            return candidate
        return None
    for idx, raw in enumerate(lines, 1):
        stripped = raw.strip()

        if not header_done:
            lower = stripped.lower()
            if (
                not stripped
                or stripped.startswith("/*")
                or stripped.startswith("*")
                or stripped.startswith("|")
                or stripped.startswith("\\")
                or stripped.startswith("//")
            ):
                continue
            if "foamfile" in lower:
                header_done = True
                continue
            header_done = True

        line = raw

        # Remove block comments while keeping text outside them.
        cleaned = ""
        remainder = line
        while remainder:
            if in_block_comment:
                end = remainder.find("*/")
                if end == -1:
                    remainder = ""
                    break
                remainder = remainder[end + 2 :]
                in_block_comment = False
                continue
            start = remainder.find("/*")
            if start == -1:
                cleaned += remainder
                break
            cleaned += remainder[:start]
            remainder = remainder[start + 2 :]
            end = remainder.find("*/")
            if end == -1:
                in_block_comment = True
                remainder = ""
            else:
                remainder = remainder[end + 2 :]

        line = cleaned
        if in_block_comment:
            # Inside a multi-line block comment; nothing to check on this line.
            continue

        # Strip single-line comments.
        if "//" in line:
            line = line.split("//", 1)[0]

        stripped_line = line.strip()
        if not stripped_line:
            continue

        # Track brace balance to flag premature closing braces.
        for ch in line:
            if ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth -= 1
                if brace_depth < 0:
                    warnings.append(f"Line {idx}: unexpected '}}'.")
                    brace_depth = 0

        # Skip blank lines and comments/includes when checking semicolons.
        if stripped_line.startswith("#include") or stripped_line.startswith("#ifdef"):
            continue
        if "{" in line and "}" in line:
            continue
        if stripped_line.endswith(";") or stripped_line.endswith("{") or stripped_line.endswith("}"):
            continue
        if stripped_line.endswith("(") or stripped_line.endswith(")"):
            continue
        next_line = next_significant_line(idx - 1)
        if next_line == "{":
            continue

        warnings.append(f"Line {idx}: missing ';'? -> {stripped_line[:60]}")

    if brace_depth > 0:
        warnings.append("File ends with unmatched '{'.")

    return warnings


def _show_message(stdscr: Any, message: str) -> None:
    stdscr.clear()
    stdscr.addstr(message + "\n")
    stdscr.addstr("Press any key to continue.\n")
    stdscr.refresh()
    stdscr.getch()


def _prompt_command(stdscr: Any, suggestions: Optional[list[str]]) -> str:
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


def _command_callbacks() -> CommandCallbacks:
    return CommandCallbacks(
        check_syntax=_check_syntax_screen,
        tools_screen=tools_screen,
        diagnostics_screen=diagnostics_screen,
        run_current_solver=run_current_solver,
        show_message=_show_message,
    )


def _browser_callbacks(case_path: Path, state: AppState) -> BrowserCallbacks:
    cmd_callbacks = _command_callbacks()

    def handle_cmd(stdscr: Any, path: Path, app_state: AppState, cmd: str) -> Optional[str]:
        return handle_command(stdscr, path, app_state, cmd, cmd_callbacks)

    return BrowserCallbacks(
        show_message=_show_message,
        view_file=_view_file_screen,
        prompt_command=_prompt_command,
        command_suggestions=command_suggestions,
        handle_command=handle_cmd,
        mode_status=_mode_status,
    )


def _status_with_check(state: AppState, base: str) -> str:
    status = state.check_status_line()
    if not status:
        return base
    if not base:
        return status
    return f"{base} | {status}"


def _mode_status(state: AppState) -> str:
    mode = "no-foam" if state.no_foam else "foam"
    wm_dir = os.environ.get("WM_PROJECT_DIR")
    suffix = f" ({wm_dir})" if wm_dir else ""
    return f"mode: {mode}{suffix}"


def _start_check_thread(case_path: Path, state: AppState) -> None:
    def worker() -> None:
        sections = discover_case_files(case_path)
        total = sum(len(files) for files in sections.values())
        with state.check_lock:
            state.check_in_progress = True
            state.check_total = total
            state.check_done = 0
            state.check_current = None
            state.check_results = {}

        def progress_callback(path: Path) -> None:
            with state.check_lock:
                state.check_done += 1
                state.check_current = path

        def result_callback(path: Path, result: FileCheckResult) -> None:
            with state.check_lock:
                if state.check_results is None:
                    state.check_results = {}
                state.check_results[path] = result

        try:
            results = verify_case(
                case_path, progress=progress_callback, result_callback=result_callback
            )
        except (OpenFOAMError, OSError):
            results = {}
        with state.check_lock:
            state.check_results = results
            state.check_in_progress = False

    thread = threading.Thread(target=worker, daemon=True)
    state.check_thread = thread
    thread.start()


def _color_from_name(value: str, default: int) -> int:
    mapping = {
        "black": curses.COLOR_BLACK,
        "red": curses.COLOR_RED,
        "green": curses.COLOR_GREEN,
        "yellow": curses.COLOR_YELLOW,
        "blue": curses.COLOR_BLUE,
        "magenta": curses.COLOR_MAGENTA,
        "cyan": curses.COLOR_CYAN,
        "white": curses.COLOR_WHITE,
    }
    return mapping.get(value.strip().lower(), default)


def _check_syntax_screen(stdscr: Any, case_path: Path, state: AppState) -> None:
    if state.check_in_progress:
        pass
    if state.check_results is None and not state.check_in_progress:
        _start_check_thread(case_path, state)

    _check_syntax_menu(stdscr, case_path, state)


def _check_syntax_menu(stdscr: Any, case_path: Path, state: AppState) -> None:
    cfg = get_config()
    sections = discover_case_files(case_path)
    files: list[Path] = []
    for group in sections.values():
        files.extend(group)
    if not files:
        _show_message(stdscr, "No case files found to check.")
        return

    current = 0
    scroll = 0
    stdscr.timeout(200)
    try:
        while True:
            labels, checks = _check_labels(case_path, files, state)
            status = _status_with_check(state, "Check syntax")
            status = f"{status} | {_mode_status(state)}" if status else _mode_status(state)
            _draw_check_menu(stdscr, labels, checks, current, scroll, status)
            key = stdscr.getch()
            if key == -1:
                continue
            if key in (curses.KEY_UP,) or key_in(key, cfg.keys.get("up", [])):
                current = (current - 1) % len(labels)
            elif key in (curses.KEY_DOWN,) or key_in(key, cfg.keys.get("down", [])):
                current = (current + 1) % len(labels)
            elif key_in(key, cfg.keys.get("top", [])):
                current = 0
            elif key_in(key, cfg.keys.get("bottom", [])):
                current = len(labels) - 1
            elif key_in(key, cfg.keys.get("back", [])):
                return
            elif key_in(key, cfg.keys.get("help", [])):
                _show_message(
                    stdscr,
                    "Check syntax menu\n\nEnter: view result, q/h: back\n\nProgress is shown in the status bar.",
                )
            elif key_in(key, cfg.keys.get("command", [])):
                callbacks = _command_callbacks()
                command = _prompt_command(stdscr, command_suggestions(case_path))
                if command and handle_command(stdscr, case_path, state, command, callbacks) == "quit":
                    return
            elif key_in(key, cfg.keys.get("select", [])):
                file_path = files[current]
                check = checks[current]
                rel = file_path.relative_to(case_path)
                if check is None or not check.checked:
                    _show_message(stdscr, f"{rel} not checked yet.")
                    continue
                if _show_check_result(stdscr, rel, check):
                    _view_file_screen(stdscr, file_path)

            scroll = _menu_scroll(current, scroll, stdscr, len(labels), header_rows=3)
    finally:
        stdscr.timeout(-1)


def _check_labels(
    case_path: Path, files: list[Path], state: AppState
) -> tuple[list[str], list[Optional[FileCheckResult]]]:
    labels: list[str] = []
    checks: list[Optional[FileCheckResult]] = []
    results = state.check_results or {}
    for file_path in files:
        rel = file_path.relative_to(case_path)
        check = results.get(file_path)
        checks.append(check)
        if check is None or not check.checked:
            status = "Not checked"
        elif check.errors:
            status = f"ERROR ({len(check.errors)})"
        elif check.warnings:
            status = f"Warn ({len(check.warnings)})"
        else:
            status = "OK"
        labels.append(f"{rel}: {status}")
    return labels, checks


def _draw_check_menu(
    stdscr: Any,
    labels: list[str],
    checks: list[Optional[FileCheckResult]],
    current: int,
    scroll: int,
    status: str,
) -> None:
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    header = "Check syntax – select file"
    try:
        stdscr.addstr(0, 0, header[: max(1, width - 1)])
        stdscr.addstr(1, 0, "Enter: view result  q/h: back"[: max(1, width - 1)])
    except curses.error:
        pass

    start_row = 3
    visible = max(0, height - start_row - 1)
    for idx in range(scroll, min(len(labels), scroll + visible)):
        prefix = ">> " if idx == current else "   "
        line = f"{prefix}{labels[idx]}"
        is_checked = checks[idx] is not None and checks[idx].checked
        try:
            if is_checked:
                stdscr.attron(curses.A_BOLD)
            stdscr.addstr(start_row + (idx - scroll), 0, line[: max(1, width - 1)])
            if is_checked:
                stdscr.attroff(curses.A_BOLD)
        except curses.error:
            break

    draw_status_bar(stdscr, status)


def _menu_scroll(
    current: int, scroll: int, stdscr: Any, total: int, header_rows: int
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
    if scroll > max_scroll:
        scroll = max_scroll
    return scroll


def _show_progress(stdscr: Any, message: str) -> None:
    stdscr.clear()
    try:
        stdscr.addstr(message + "\n")
    except curses.error:
        pass
    stdscr.refresh()


def _show_check_result(stdscr: Any, rel_path: Path, result: FileCheckResult) -> bool:
    status = "OK"
    if not result.checked:
        status = "NOT CHECKED"
    elif result.errors:
        status = "ERROR"
    elif result.warnings:
        status = "Warnings"

    stdscr.clear()
    line = f"{rel_path}: {status}"
    try:
        stdscr.addstr(line + "\n\n")
        if not result.checked:
            stdscr.addstr("Check interrupted before this file ran.\n\n")
        elif result.errors:
            stdscr.addstr("Detected issues:\n")
            for item in result.errors:
                stdscr.addstr(f"- {item}\n")
            stdscr.addstr("\n")
        elif result.warnings:
            stdscr.addstr("Warnings:\n")
            for item in result.warnings:
                stdscr.addstr(f"- {item}\n")
            stdscr.addstr("\n")
        else:
            stdscr.addstr("No issues detected.\n\n")
        stdscr.addstr("Press 'v' to view file or any other key to return.\n")
        stdscr.refresh()
    except curses.error:
        stdscr.refresh()

    ch = stdscr.getch()
    return ch in (ord("v"), ord("V"))



def _global_search_screen(stdscr: Any, case_path: Path, state: AppState) -> None:
    """
    Global search wrapper around `fzf`.

    Lists all dictionary entries (file + key + snippet), lets the user
    fuzzy-select one via `fzf`, and then opens the editor browser at
    the chosen entry as if it was selected manually.
    """
    if not fzf_enabled():
        _show_message(stdscr, "fzf not available (disabled or missing).")
        return

    foam_case = Case(root=case_path)
    sections = discover_case_files(foam_case.root)
    entries: list[EntryRef] = []

    for _section, files in sections.items():
        for file_path in files:
            status_message(stdscr, f"Indexing {file_path.relative_to(case_path)}...")
            dict_file = DictionaryFile(foam_case.root, file_path)
            try:
                keys = list_keywords(file_path)
            except OpenFOAMError as exc:
                if state.no_foam:
                    _show_message(
                        stdscr,
                        f"Global search failed: {exc} (no-foam mode may disable OpenFOAM tools)",
                    )
                    return
                continue
            for key in keys:
                entries.append(EntryRef(dict_file, key))

    if not entries:
        _show_message(stdscr, "No entries found for global search.")
        return

    # Prepare lines for fzf: rel_path<TAB>key
    fzf_input = "\n".join(f"{ref.file.rel}\t{ref.key}" for ref in entries)

    # Temporarily suspend curses UI while running fzf.
    curses.def_prog_mode()
    curses.endwin()
    try:
        result = subprocess.run(
            ["fzf"],
            input=fzf_input,
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        # Restore curses mode and refresh the screen.
        curses.reset_prog_mode()
        stdscr.clear()
        stdscr.refresh()

    if result.returncode != 0:
        return
    selected = result.stdout.strip()
    if not selected:
        return

    parts = selected.split("\t", 1)
    if len(parts) != 2:
        return
    rel_str, full_key = parts
    file_path = case_path / rel_str

    try:
        keys = list_keywords(file_path)
    except OpenFOAMError as exc:
        _show_message(stdscr, f"Failed to load keys for {rel_str}: {exc}")
        return

    # Try to locate the key at top level.
    base_key = full_key.split(".")[-1]
    try:
        initial_index = keys.index(base_key)
    except ValueError:
        initial_index = 0

    # Jump into the entry browser at the selected key; from there user can
    # edit and navigate as if they arrived via the normal editor path.
    callbacks = _browser_callbacks(case_path, state)
    entry_browser_screen(
        stdscr,
        case_path,
        file_path,
        state,
        callbacks,
        initial_index=initial_index,
    )


def _open_file_in_editor(stdscr: Any, file_path: Path) -> None:
    editor = os.environ.get("EDITOR") or "vi"
    curses.endwin()
    try:
        subprocess.run([editor, str(file_path)], check=False)
    except OSError as exc:
        _show_message(stdscr, f"Failed to run {editor}: {exc}")
    finally:
        stdscr.clear()
        stdscr.refresh()


def _case_metadata(case_path: Path) -> dict[str, str]:
    latest_time = _latest_time(case_path)
    status = "ran" if latest_time not in ("0", "0.0", "") else "clean"
    parallel = _detect_parallel_settings(case_path)
    mesh = _detect_mesh_stats(case_path)
    return {
        "case_name": case_path.name,
        "case_path": str(case_path),
        "solver": _detect_solver(case_path),
        "foam_version": _detect_openfoam_version(),
        "case_header_version": _detect_case_header_version(case_path),
        "latest_time": latest_time,
        "status": status,
        "mesh": mesh,
        "parallel": parallel,
    }


def _detect_solver(case_path: Path) -> str:
    control_dict = case_path / "system" / "controlDict"
    if not control_dict.is_file():
        return "unknown"
    try:
        value = read_entry(control_dict, "application")
    except OpenFOAMError:
        return "unknown"
    text = value.strip()
    if not text:
        return "unknown"
    solver = text.split()[0].rstrip(";")
    return solver or "unknown"


def _detect_parallel_settings(case_path: Path) -> str:
    decompose_dict = case_path / "system" / "decomposeParDict"
    if not decompose_dict.is_file():
        return "n/a"
    number = _read_optional_entry(decompose_dict, "numberOfSubdomains")
    method = _read_optional_entry(decompose_dict, "method")
    if number and method:
        return f"{number} ({method})"
    if number:
        return number
    if method:
        return method
    return "n/a"


def _detect_mesh_stats(case_path: Path) -> str:
    log_path = _latest_checkmesh_log(case_path)
    if log_path is None:
        return "unknown"
    try:
        text = log_path.read_text(errors="ignore")
    except OSError:
        return "unknown"

    cells = _parse_cells_count(text)
    skew = _parse_max_skewness(text)
    if cells and skew:
        return f"cells={cells}, skew={skew}"
    if cells:
        return f"cells={cells}"
    if skew:
        return f"skew={skew}"
    return "unknown"


def _latest_checkmesh_log(case_path: Path) -> Optional[Path]:
    candidates = list(case_path.glob("log.checkMesh*"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _parse_cells_count(text: str) -> Optional[str]:
    match = re.search(r"(?i)number of cells\\s*:\\s*(\\d+)", text)
    if match:
        return match.group(1)
    match = re.search(r"(?i)cells\\s*:\\s*(\\d+)", text)
    if match:
        return match.group(1)
    return None


def _parse_max_skewness(text: str) -> Optional[str]:
    match = re.search(r"(?i)max\\s+skewness\\s*=\\s*([0-9eE.+-]+)", text)
    if match:
        return match.group(1)
    return None


def _read_optional_entry(file_path: Path, key: str) -> Optional[str]:
    try:
        return read_entry(file_path, key).strip()
    except OpenFOAMError:
        return None


def _detect_openfoam_version() -> str:
    for env in ("WM_PROJECT_VERSION", "FOAM_VERSION"):
        version = os.environ.get(env)
        if version:
            return version
    try:
        result = subprocess.run(
            ["foamVersion", "-short"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    version = result.stdout.strip()
    return version or "unknown"


def _detect_case_header_version(case_path: Path) -> str:
    versions: list[str] = []
    control_dict = case_path / "system" / "controlDict"
    control_version = _extract_header_version(control_dict)
    if control_version:
        versions.append(control_version)

    sample_files = _case_header_candidates(case_path, max_files=20)
    for path in sample_files:
        if path == control_dict:
            continue
        version = _extract_header_version(path)
        if version:
            versions.append(version)

    if not versions:
        return "unknown"

    counts: dict[str, int] = {}
    for version in versions:
        counts[version] = counts.get(version, 0) + 1

    best_count = max(counts.values())
    best_versions = [v for v, count in counts.items() if count == best_count]
    if control_version and control_version in best_versions:
        return control_version
    return sorted(best_versions)[0]


def _parse_header_comment_version(text: str) -> Optional[str]:
    """
    Extract the version string from the ASCII banner that precedes FoamFile.
    """
    version_pattern = re.compile(r"Version:\s*([^\s|]+)", re.IGNORECASE)
    for line in text.splitlines():
        lower = line.lower()
        if "foamfile" in lower:
            break
        match = version_pattern.search(line)
        if match:
            value = match.group(1).strip().strip("|")
            if value:
                return value
    return None


def _parse_foamfile_block_version(text: str) -> Optional[str]:
    """
    Fallback: read the 'version' entry inside the FoamFile dictionary block.
    """
    inside_block = False
    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("foamfile"):
            inside_block = True
            continue
        if inside_block and stripped.startswith("}"):
            break
        if inside_block and lower.startswith("version"):
            parts = stripped.split()
            if len(parts) >= 2:
                value = parts[1].rstrip(";")
                if value:
                    return value
    return None


def _extract_header_version(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    try:
        text = path.read_text()
    except OSError:
        return None
    header_version = _parse_header_comment_version(text)
    if header_version:
        return header_version
    return _parse_foamfile_block_version(text)


def _case_header_candidates(case_path: Path, max_files: int = 20) -> list[Path]:
    candidates: list[Path] = []
    for rel in ("system", "constant", "0"):
        folder = case_path / rel
        if not folder.is_dir():
            continue
        for entry in sorted(folder.iterdir()):
            if entry.is_file():
                candidates.append(entry)
            if len(candidates) >= max_files:
                return candidates
    return candidates


def _latest_time(case_path: Path) -> str:
    latest_value = 0.0
    found = False
    for entry in case_path.iterdir():
        if not entry.is_dir():
            continue
        try:
            value = float(entry.name)
        except ValueError:
            continue
        if not found or value > latest_value:
            latest_value = value
            found = True
    return f"{latest_value:g}" if found else "0"

from __future__ import annotations

import curses
import logging
import os
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ofti.app.commands import CommandCallbacks, command_suggestions, handle_command
from ofti.core.case import detect_mesh_stats, detect_parallel_settings, detect_solver
from ofti.core.case_headers import detect_case_header_version
from ofti.core.domain import Case, DictionaryFile, EntryRef
from ofti.core.entries import Entry, autoformat_value
from ofti.core.entry_meta import choose_validator
from ofti.core.syntax import find_suspicious_lines
from ofti.core.times import latest_time
from ofti.foam.config import fzf_enabled, get_config, key_hint, key_in
from ofti.foam.exceptions import QuitAppError
from ofti.foam.openfoam import (
    FileCheckResult,
    OpenFOAMError,
    discover_case_files,
    list_keywords,
    list_subkeys,
    read_entry,
    verify_case,
    write_entry,
)
from ofti.foam.openfoam_env import detect_openfoam_version, ensure_environment
from ofti.foam.subprocess_utils import resolve_executable, run_trusted
from ofti.foam.tasks import Task, TaskRegistry
from ofti.tools import (
    clone_case,
    diagnostics_screen,
    dictionary_linter_screen,
    log_tail_screen,
    logs_screen,
    reconstruct_manager_screen,
    run_checkmesh,
    run_current_solver,
    run_tool_by_name,
    safe_stop_screen,
    solver_resurrection_screen,
    time_directory_pruner_screen,
    tools_screen,
)
from ofti.ui_curses.boundary_matrix import boundary_matrix_screen
from ofti.ui_curses.entry_browser import BrowserCallbacks, entry_browser_screen
from ofti.ui_curses.entry_editor import EntryEditor
from ofti.ui_curses.layout import (
    case_banner_lines,
    case_overview_lines,
    draw_status_bar,
    next_spinner,
    status_message,
)
from ofti.ui_curses.menus import Menu, RootMenu, Submenu
from ofti.ui_curses.openfoam_env import openfoam_env_screen
from ofti.ui_curses.viewer import Viewer


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
    no_foam_reason: str | None = None
    current_screen: Screen = Screen.MAIN_MENU
    last_action: str | None = None
    last_section: str | None = None
    last_file: str | None = None
    menu_selection: dict[str, int] = field(default_factory=dict)
    check_lock: threading.Lock = field(default_factory=threading.Lock)
    check_in_progress: bool = False
    check_total: int = 0
    check_done: int = 0
    check_current: Path | None = None
    check_results: dict[Path, FileCheckResult] | None = None
    check_thread: threading.Thread | None = None
    tasks: TaskRegistry = field(default_factory=TaskRegistry)

    def transition(self, screen: Screen, action: str | None = None) -> None:
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
    input_path = Path(case_dir).expanduser().resolve()
    start_path = input_path.parent if input_path.is_file() else input_path
    state = AppState(no_foam=no_foam)
    if no_foam:
        os.environ["OFTI_NO_FOAM"] = "1"
    else:
        os.environ.pop("OFTI_NO_FOAM", None)
    curses.wrapper(_main, start_path, debug, state)


def _main(stdscr: Any, case_path: Path, debug: bool, state: AppState) -> None:
    curses.start_color()
    cfg = get_config()
    fg = _color_from_name(cfg.colors.get("focus_fg", "black"), curses.COLOR_BLACK)
    bg = _color_from_name(cfg.colors.get("focus_bg", "cyan"), curses.COLOR_CYAN)
    curses.init_pair(1, fg, bg)

    if not _is_case_dir(case_path):
        selected = _select_case_directory(stdscr, case_path)
        if selected is None:
            return
        case_path = selected

    if not state.no_foam:
        try:
            ensure_environment()
        except OpenFOAMError as exc:
            state.no_foam = True
            state.no_foam_reason = str(exc)
            os.environ["OFTI_NO_FOAM"] = "1"

    try:
        _main_loop(stdscr, case_path, state)
    except QuitAppError:
        return
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

    next_screen: Screen | None = Screen.MAIN_MENU
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
    stdscr: Any, case_path: Path, state: AppState,
) -> Screen | None:
    state.transition(Screen.MAIN_MENU)
    has_fzf = fzf_enabled()

    categories = [
        "Pre-Processing (Mesh)",
        "Physics & Boundary Conditions",
        "Simulation (Run)",
        "Post-Processing",
        "Config Manager",
        "Tools / Diagnostics",
    ]
    menu_options = list(categories)
    quit_index = len(menu_options)
    menu_options.append("Quit")

    case_meta = _case_metadata(case_path)
    banner_lines = case_banner_lines(case_meta)
    overview_lines = case_overview_lines(case_meta)
    callbacks = _command_callbacks()
    initial_index = state.menu_selection.get("menu:root", 0)
    root_menu = RootMenu(
        stdscr,
        "Main menu",
        menu_options,
        extra_lines=overview_lines,
        banner_lines=banner_lines,
        initial_index=initial_index,
        command_handler=lambda cmd: handle_command(
            stdscr, case_path, state, cmd, callbacks,
        ),
        command_suggestions=lambda: command_suggestions(case_path),
        status_line=_menu_status_line(state),
    )
    choice = root_menu.navigate()
    if choice in (-1, quit_index):
        return None
    state.menu_selection["menu:root"] = choice

    if choice == 0:
        return _preprocessing_menu(stdscr, case_path, state)
    if choice == 1:
        return _physics_menu(stdscr, case_path, state)
    if choice == 2:
        return _simulation_menu(stdscr, case_path, state)
    if choice == 3:
        return _postprocessing_menu(stdscr, case_path, state)
    if choice == 4:
        return _config_manager_menu(stdscr, case_path, state, has_fzf)
    if choice == 5:
        return _tools_diag_menu(stdscr, case_path, state)
    return Screen.MAIN_MENU


def _select_case_file(
    stdscr: Any,
    case_path: Path,
    state: AppState,
    sections: dict[str, list[Path]],
) -> Path | None:
    section_names = [name for name, files in sections.items() if files]
    if not section_names:
        _show_message(stdscr, "No OpenFOAM case files found in this case.")
        return None
    section_index = _option_index(section_names, state.last_section)

    while True:
        callbacks = _command_callbacks()
        section_menu = Menu(
            stdscr,
            "Editor - select section",
            [*section_names, "Back"],
            initial_index=section_index,
            command_handler=lambda cmd, cb=callbacks: handle_command(
                stdscr, case_path, state, cmd, cb,
            ),
            command_suggestions=lambda: command_suggestions(case_path),
        )
        section_index = section_menu.navigate()
        if section_index == -1 or section_index == len(section_names):
            return None

        section = section_names[section_index]
        state.last_section = section
        files = sections.get(section, [])
        if not files:
            _show_message(stdscr, f"No files found in section {section}.")
            continue

        file_labels = [f.relative_to(case_path).as_posix() for f in files]
        file_index = _option_index(file_labels, state.last_file)
        while True:
            callbacks = _command_callbacks()
            file_menu = Menu(
                stdscr,
                f"{section} files",
                [*file_labels, "Back"],
                initial_index=file_index,
                command_handler=lambda cmd, cb=callbacks: handle_command(
                    stdscr, case_path, state, cmd, cb,
                ),
                command_suggestions=lambda: command_suggestions(case_path),
            )
            file_index = file_menu.navigate()
            if file_index == -1 or file_index == len(file_labels):
                break
            state.last_file = file_labels[file_index]
            return files[file_index]


def _editor_screen(stdscr: Any, case_path: Path, state: AppState) -> None:
    sections = _simple_case_sections(case_path)
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
            callbacks = _browser_callbacks()
            entry_browser_screen(stdscr, case_path, file_path, state, callbacks)


def _simple_case_sections(case_path: Path) -> dict[str, list[Path]]:
    """
    Noice-style case crawl: scan only top-level files in system/constant/0*.
    """
    sections: dict[str, list[Path]] = {}

    def add_section(name: str, folder: Path) -> None:
        entries = _scan_dir_files(folder)
        if entries:
            sections[name] = entries

    add_section("system", case_path / "system")
    add_section("constant", case_path / "constant")

    for zero_dir in _scan_zero_dirs(case_path):
        add_section(zero_dir.name, zero_dir)

    return sections


def _scan_dir_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    entries: list[Path] = []
    try:
        for entry in os.scandir(folder):
            if not entry.is_file():
                continue
            if entry.name.startswith(".") or entry.name.endswith("~"):
                continue
            entries.append(Path(entry.path))
    except OSError:
        return []
    return sorted(entries)


def _scan_zero_dirs(case_path: Path) -> list[Path]:
    zero_dirs: list[Path] = []
    try:
        zero_dirs.extend(
            Path(entry.path)
            for entry in os.scandir(case_path)
            if entry.is_dir() and entry.name.startswith("0")
        )
    except OSError:
        return []
    return sorted(zero_dirs)


def _file_screen(stdscr: Any, case_path: Path, file_path: Path, state: AppState) -> None:
    try:
        keywords = list_keywords(file_path)
    except OpenFOAMError as exc:
        stdscr.clear()
        stdscr.addstr(f"Error reading {file_path.relative_to(case_path)}:\n")
        stdscr.addstr(str(exc) + "\n")
        back_hint = key_hint("back", "h")
        stdscr.addstr(f"Press {back_hint} to go back.\n")
        stdscr.refresh()
        stdscr.getch()
        return

    options = ["Edit entry", "View file", "Back"]
    callbacks = _command_callbacks()
    submenu = Submenu(
        stdscr,
        f"{file_path.relative_to(case_path)}",
        options[:-1],
        command_handler=lambda cmd: handle_command(
            stdscr, case_path, state, cmd, callbacks,
        ),
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
    stdscr: Any, case_path: Path, file_path: Path, state: AppState,
) -> None:
    options = ["View file", "Open in $EDITOR", "Back"]
    while True:
        callbacks = _command_callbacks()
        menu = Menu(
            stdscr,
            f"{file_path.relative_to(case_path)}",
            options,
            command_handler=lambda cmd, cb=callbacks: handle_command(
                stdscr, case_path, state, cmd, cb,
            ),
            command_suggestions=lambda: command_suggestions(case_path),
            status_line=_menu_status_line(state),
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
    keywords: list[str],
    state: AppState,
    base_entry: str | None = None,
) -> None:
    if not keywords:
        _show_message(stdscr, "No entries found in file.")
        return

    callbacks = _command_callbacks()
    entry_menu = Menu(
        stdscr,
        "Select entry to edit",
        [*keywords, "Back"],
        command_handler=lambda cmd, cb=callbacks: handle_command(
            stdscr, case_path, state, cmd, cb,
        ),
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
            command_handler=lambda cmd: handle_command(
                stdscr, case_path, state, cmd, callbacks,
            ),
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

    warnings = find_suspicious_lines(content)
    if warnings:
        warning_text = "\n".join(["Suspicious lines detected:", *warnings, "", content])
    else:
        warning_text = content

    viewer = Viewer(stdscr, warning_text)
    viewer.display()



def _option_index(options: list[str], selection: str | None) -> int:
    if not selection:
        return 0
    try:
        return options.index(selection)
    except ValueError:
        return 0


def _show_message(stdscr: Any, message: str) -> None:
    stdscr.clear()
    stdscr.addstr(message + "\n")
    stdscr.addstr("Press any key to continue.\n")
    stdscr.refresh()
    key = stdscr.getch()
    if key_in(key, get_config().keys.get("quit", [])):
        raise QuitAppError()


def _is_case_dir(path: Path) -> bool:
    return (path / "system" / "controlDict").is_file()


def _list_dir_entries(path: Path) -> tuple[list[Path], list[Path]]:
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


def _select_case_directory(stdscr: Any, start_path: Path) -> Path | None:
    current = start_path if start_path.is_dir() else start_path.parent
    index = 0
    scroll = 0
    cfg = get_config()

    while True:
        dirs, files = _list_dir_entries(current)
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

        scroll = _menu_scroll(index, scroll, stdscr, len(labels), header_rows=3)
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
            if _is_case_dir(current):
                return current
            _show_message(stdscr, "Not an OpenFOAM case (missing system/controlDict).")
            continue
        if key in (curses.KEY_ENTER, 10, 13) or key_in(key, cfg.keys.get("select", [])):
            label, path = entries[index]
            if label == "[Use this folder]":
                if _is_case_dir(current):
                    return current
                _show_message(stdscr, "Not an OpenFOAM case (missing system/controlDict).")
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
            _show_message(stdscr, f"{path.name} is not a folder.")


def _tasks_screen(stdscr: Any, state: AppState) -> None:
    tasks = state.tasks.list_tasks()
    if not tasks:
        _show_message(stdscr, "No background tasks running.")
        return
    lines = ["Background tasks:"]
    for task in sorted(tasks, key=lambda item: item.name):
        message = f" - {task.message}" if task.message else ""
        lines.append(f"{task.name}: {task.status}{message}")
    lines.append("")
    lines.append("Use :cancel <task-name> to stop a task.")
    viewer = Viewer(stdscr, "\n".join(lines))
    viewer.display()


def _prompt_command(stdscr: Any, suggestions: list[str] | None) -> str:
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
        tasks_screen=_tasks_screen,
        openfoam_env_screen=openfoam_env_screen,
        clone_case=clone_case,
        search_screen=_global_search_screen,
    )


def _browser_callbacks() -> BrowserCallbacks:
    cmd_callbacks = _command_callbacks()

    def handle_cmd(stdscr: Any, path: Path, app_state: AppState, cmd: str) -> str | None:
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
    def worker(task: Task) -> None:
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
            task.message = path.name
            if task.cancel.is_set():
                raise KeyboardInterrupt

        def result_callback(path: Path, result: FileCheckResult) -> None:
            with state.check_lock:
                if state.check_results is None:
                    state.check_results = {}
                state.check_results[path] = result

        try:
            results = verify_case(
                case_path, progress=progress_callback, result_callback=result_callback,
            )
        except (OpenFOAMError, OSError):
            results = {}
            task.status = "error"
        except KeyboardInterrupt:
            results = state.check_results or {}
            task.status = "canceled"
        else:
            task.status = "done"
        with state.check_lock:
            state.check_results = results
            state.check_in_progress = False
    task = state.tasks.start("check_syntax", worker, message="Starting checks")
    state.check_thread = task.thread


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
    cfg = get_config()
    if not cfg.enable_background_checks:
        sections = discover_case_files(case_path)
        total = sum(len(files) for files in sections.values())
        with state.check_lock:
            state.check_in_progress = True
            state.check_total = total
            state.check_done = 0
            state.check_current = None
            state.check_results = {}
        status_message(stdscr, "Checking syntax...")
        try:
            results = verify_case(case_path)
        except (OpenFOAMError, OSError):
            results = {}
        with state.check_lock:
            state.check_results = results
            state.check_done = total
            state.check_in_progress = False
        _check_syntax_menu(stdscr, case_path, state)
        return

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
                back_hint = key_hint("back", "h")
                _show_message(
                    stdscr,
                    "Check syntax menu\n\n"
                    f"Enter: view result, {back_hint}: back\n\n"
                    "Includes required-entries linter. Progress is shown in the status bar.",
                )
            elif key_in(key, cfg.keys.get("command", [])):
                callbacks = _command_callbacks()
                command = _prompt_command(stdscr, command_suggestions(case_path))
                if (
                    command
                    and handle_command(stdscr, case_path, state, command, callbacks) == "quit"
                ):
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
    case_path: Path, files: list[Path], state: AppState,
) -> tuple[list[str], list[FileCheckResult | None]]:
    labels: list[str] = []
    checks: list[FileCheckResult | None] = []
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
    checks: list[FileCheckResult | None],
    current: int,
    scroll: int,
    status: str,
) -> None:
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    header = "Check syntax - select file"
    try:
        stdscr.addstr(0, 0, header[: max(1, width - 1)])
        back_hint = key_hint("back", "h")
        stdscr.addstr(
            1,
            0,
            f"Enter: view result  {back_hint}: back"[: max(1, width - 1)],
        )
    except curses.error:
        pass

    start_row = 3
    visible = max(0, height - start_row - 1)
    for idx in range(scroll, min(len(labels), scroll + visible)):
        prefix = ">> " if idx == current else "   "
        line = f"{prefix}{labels[idx]}"
        check = checks[idx]
        is_checked = check.checked if check is not None else False
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


def _menu_choice(
    stdscr: Any,
    title: str,
    options: list[str],
    state: AppState,
    menu_key: str,
    command_handler: Callable[[str], str | None] | None = None,
    command_suggestions: Callable[[], list[str]] | None = None,
    disabled_indices: set[int] | None = None,
    status_line: str | None = None,
) -> int:
    initial_index = state.menu_selection.get(menu_key, 0)
    menu = Menu(
        stdscr,
        title,
        options,
        initial_index=initial_index,
        command_handler=command_handler,
        command_suggestions=command_suggestions,
        disabled_indices=disabled_indices,
        status_line=status_line,
    )
    choice = menu.navigate()
    if choice >= 0:
        state.menu_selection[menu_key] = choice
    return choice


def _menu_status_line(state: AppState) -> str | None:
    if not state.no_foam:
        return None
    return "Limited mode: OpenFOAM env not found (simple editor only)"


def _preprocessing_menu(stdscr: Any, case_path: Path, state: AppState) -> Screen:
    options = [
        "Run blockMesh",
        "Mesh quality (checkMesh)",
        "Decompose (decomposePar)",
        "Reconstruct (manager)",
        "Back",
    ]
    disabled = set(range(len(options) - 1)) if state.no_foam else None
    while True:
        choice = _menu_choice(
            stdscr,
            "Pre-Processing (Mesh)",
            options,
            state,
            "menu:pre",
            disabled_indices=disabled,
            status_line=_menu_status_line(state),
        )
        if choice in (-1, len(options) - 1):
            return Screen.MAIN_MENU
        if choice == 0:
            run_tool_by_name(stdscr, case_path, "blockMesh")
        elif choice == 1:
            run_checkmesh(stdscr, case_path)
        elif choice == 2:
            run_tool_by_name(stdscr, case_path, "decomposePar")
        elif choice == 3:
            reconstruct_manager_screen(stdscr, case_path)


def _physics_menu(stdscr: Any, case_path: Path, state: AppState) -> Screen:
    options = [
        "Config Editor",
        "Boundary matrix",
        "Check syntax",
        "Dictionary linter (required keys)",
        "Back",
    ]
    disabled = {1, 2, 3} if state.no_foam else None
    while True:
        choice = _menu_choice(
            stdscr,
            "Physics & Boundary Conditions",
            options,
            state,
            "menu:physics",
            disabled_indices=disabled,
            status_line=_menu_status_line(state),
        )
        if choice in (-1, len(options) - 1):
            return Screen.MAIN_MENU
        if choice == 0:
            _editor_screen(stdscr, case_path, state)
        elif choice == 1:
            boundary_matrix_screen(stdscr, case_path)
        elif choice == 2:
            _check_syntax_screen(stdscr, case_path, state)
        elif choice == 3:
            dictionary_linter_screen(stdscr, case_path)


def _simulation_menu(stdscr: Any, case_path: Path, state: AppState) -> Screen:
    options = [
        "Run current solver",
        "Safe stop (create stop file)",
        "Resume solver (latestTime)",
        "foamJob (run job)",
        "foamEndJob (stop job)",
        "Job status (poll)",
        "Back",
    ]
    disabled = set(range(len(options) - 1)) if state.no_foam else None
    while True:
        choice = _menu_choice(
            stdscr,
            "Simulation (Run)",
            options,
            state,
            "menu:sim",
            disabled_indices=disabled,
            status_line=_menu_status_line(state),
        )
        if choice in (-1, len(options) - 1):
            return Screen.MAIN_MENU
        if choice == 0:
            run_current_solver(stdscr, case_path)
        elif choice == 1:
            safe_stop_screen(stdscr, case_path)
        elif choice == 2:
            solver_resurrection_screen(stdscr, case_path)
        elif choice == 3:
            run_tool_by_name(stdscr, case_path, "foamJob")
        elif choice == 4:
            run_tool_by_name(stdscr, case_path, "foamEndJob")
        elif choice == 5:
            run_tool_by_name(stdscr, case_path, "jobStatus")


def _postprocessing_menu(stdscr: Any, case_path: Path, state: AppState) -> Screen:
    options = [
        "Reconstruct manager",
        "Time directory pruner",
        "Tail log (highlight)",
        "View logs",
        "postProcess (prompt)",
        "foamCalc (prompt)",
        "Run .sh script",
        "Back",
    ]
    disabled = set(range(len(options) - 1)) if state.no_foam else None
    while True:
        choice = _menu_choice(
            stdscr,
            "Post-Processing",
            options,
            state,
            "menu:post",
            disabled_indices=disabled,
            status_line=_menu_status_line(state),
        )
        if choice in (-1, len(options) - 1):
            return Screen.MAIN_MENU
        if choice == 0:
            reconstruct_manager_screen(stdscr, case_path)
        elif choice == 1:
            time_directory_pruner_screen(stdscr, case_path)
        elif choice == 2:
            log_tail_screen(stdscr, case_path)
        elif choice == 3:
            logs_screen(stdscr, case_path)
        elif choice == 4:
            run_tool_by_name(stdscr, case_path, "postProcess")
        elif choice == 5:
            run_tool_by_name(stdscr, case_path, "foamCalc")
        elif choice == 6:
            run_tool_by_name(stdscr, case_path, "runScript")


def _config_manager_menu(
    stdscr: Any, case_path: Path, state: AppState, has_fzf: bool,
) -> Screen:
    options = [
        "Config Editor",
        "OpenFOAM environment",
        "Check syntax",
        "Dictionary linter (required keys)",
    ]
    if has_fzf:
        options.append("Search")
    options.append("Back")
    cfg = get_config()
    original_search = list(cfg.keys.get("search", []))
    if "s" not in original_search:
        cfg.keys["search"] = [*original_search, "s"]
    try:
        while True:
            disabled = None
            if state.no_foam:
                disabled = {2, 3}
                if has_fzf:
                    disabled.add(4)
            choice = _menu_choice(
                stdscr,
                "Config Manager",
                options,
                state,
                "menu:config",
                disabled_indices=disabled,
                status_line=_menu_status_line(state),
            )
            if choice in (-1, len(options) - 1):
                return Screen.MAIN_MENU
            if choice == 0:
                _editor_screen(stdscr, case_path, state)
            elif choice == 1:
                openfoam_env_screen(stdscr)
            elif choice == 2:
                _check_syntax_screen(stdscr, case_path, state)
            elif choice == 3:
                dictionary_linter_screen(stdscr, case_path)
            elif has_fzf and choice == 4:
                _global_search_screen(stdscr, case_path, state)
    finally:
        cfg.keys["search"] = original_search


def _tools_diag_menu(stdscr: Any, case_path: Path, state: AppState) -> Screen:
    options = [
        "Other tools",
        "Other diagnostics",
        "Back",
    ]
    disabled = {0, 1} if state.no_foam else None
    while True:
        choice = _menu_choice(
            stdscr,
            "Tools / Diagnostics",
            options,
            state,
            "menu:tools",
            disabled_indices=disabled,
            status_line=_menu_status_line(state),
        )
        if choice in (-1, len(options) - 1):
            return Screen.MAIN_MENU
        if choice == 0:
            tools_screen(stdscr, case_path)
        elif choice == 1:
            diagnostics_screen(stdscr, case_path)


def _show_progress(stdscr: Any, message: str) -> None:
    stdscr.clear()
    with suppress(curses.error):
        stdscr.addstr(message + "\n")
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
        view_hint = key_hint("view", "v")
        back_hint = key_hint("back", "h")
        stdscr.addstr(f"Press {view_hint} to view file or {back_hint} to return.\n")
        stdscr.refresh()
    except curses.error:
        stdscr.refresh()

    ch = stdscr.getch()
    return key_in(ch, get_config().keys.get("view", []))



def _global_search_screen(
    stdscr: Any, case_path: Path, state: AppState,
) -> None:
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

    for files in sections.values():
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
            entries.extend(EntryRef(dict_file, key) for key in keys)

    if not entries:
        _show_message(stdscr, "No entries found for global search.")
        return

    # Prepare lines for fzf: rel_path<TAB>key
    fzf_input = "\n".join(f"{ref.file.rel}\t{ref.key}" for ref in entries)

    # Temporarily suspend curses UI while running fzf.
    curses.def_prog_mode()
    curses.endwin()
    try:
        try:
            result = run_trusted(
                ["fzf"],
                stdin=fzf_input,
                text=True,
                capture_output=True,
                check=False,
            )
        except FileNotFoundError:
            _show_message(stdscr, "fzf not found.")
            return
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
    callbacks = _browser_callbacks()
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
        resolved = resolve_executable(editor)
        run_trusted([resolved, str(file_path)], capture_output=False, check=False)
    except OSError as exc:
        _show_message(stdscr, f"Failed to run {editor}: {exc}")
    finally:
        stdscr.clear()
        stdscr.refresh()


def _case_metadata(case_path: Path) -> dict[str, str]:
    latest = latest_time(case_path)
    status = "ran" if latest not in ("0", "0.0", "") else "clean"
    parallel = detect_parallel_settings(case_path)
    mesh = _detect_mesh_stats(case_path)
    return {
        "case_name": case_path.name,
        "case_path": str(case_path),
        "solver": detect_solver(case_path),
        "foam_version": detect_openfoam_version(),
        "case_header_version": detect_case_header_version(case_path),
        "latest_time": latest,
        "status": status,
        "mesh": mesh,
        "parallel": parallel,
    }


def _detect_mesh_stats(case_path: Path) -> str:
    return detect_mesh_stats(case_path)

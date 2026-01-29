from __future__ import annotations

import curses
import logging
import os
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from ofti.app.commands import CommandCallbacks, command_suggestions, handle_command
from ofti.app.helpers import (
    is_case_dir,
    menu_scroll,
    option_index,
    prompt_command,
    select_case_directory,
    set_no_foam_mode,
    show_message,
)
from ofti.app.state import AppState, Screen
from ofti.core.case import detect_mesh_stats, detect_parallel_settings, detect_solver
from ofti.core.case_headers import detect_case_header_version
from ofti.core.domain import Case, DictionaryFile, EntryRef
from ofti.core.entries import Entry, autoformat_value
from ofti.core.entry_io import list_keywords, list_subkeys, read_entry, write_entry
from ofti.core.entry_meta import choose_validator, detect_type_with_foamlib
from ofti.core.syntax import find_suspicious_lines
from ofti.core.times import latest_time
from ofti.core.versioning import get_dict_path
from ofti.foam.config import fzf_enabled, get_config, key_hint, key_in
from ofti.foam.exceptions import QuitAppError
from ofti.foam.openfoam import FileCheckResult, OpenFOAMError, discover_case_files, verify_case
from ofti.foam.openfoam_env import detect_openfoam_version, ensure_environment
from ofti.foam.subprocess_utils import resolve_executable, run_trusted
from ofti.foam.tasks import Task
from ofti.foamlib_adapter import available as foamlib_available
from ofti.tools import (
    clean_case,
    clean_time_directories,
    clone_case,
    diagnostics_screen,
    foamlib_parametric_study_screen,
    log_tail_screen,
    logs_screen,
    probes_viewer_screen,
    reconstruct_manager_screen,
    remove_all_logs,
    residual_timeline_screen,
    run_checkmesh,
    run_current_solver,
    run_current_solver_live,
    run_tool_by_name,
    safe_stop_screen,
    solver_resurrection_screen,
    time_directory_pruner_screen,
    tools_screen,
    yplus_screen,
)
from ofti.ui.adapter import CursesAdapter
from ofti.ui.router import ScreenRouter
from ofti.ui_curses.blockmesh_helper import blockmesh_helper_screen
from ofti.ui_curses.boundary_matrix import boundary_matrix_screen
from ofti.ui_curses.entry_browser import BrowserCallbacks, entry_browser_screen
from ofti.ui_curses.entry_editor import EntryEditor
from ofti.ui_curses.help import (
    clean_case_help,
    config_help,
    main_menu_help,
    physics_help,
    postprocessing_help,
    preprocessing_help,
    simulation_help,
)
from ofti.ui_curses.high_speed import high_speed_helper_screen
from ofti.ui_curses.layout import (
    case_banner_lines,
    case_overview_lines,
    draw_status_bar,
    status_message,
)
from ofti.ui_curses.menus import Menu, RootMenu, Submenu
from ofti.ui_curses.openfoam_env import openfoam_env_screen
from ofti.ui_curses.snappy_toggle import snappy_staged_screen
from ofti.ui_curses.thermo_wizard import thermophysical_wizard_screen
from ofti.ui_curses.viewer import Viewer


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
    set_no_foam_mode(state, no_foam)
    curses.wrapper(_main, start_path, debug, state)


def _main(stdscr: Any, case_path: Path, debug: bool, state: AppState) -> None:
    curses.start_color()
    cfg = get_config()
    fg = _color_from_name(cfg.colors.get("focus_fg", "black"), curses.COLOR_BLACK)
    bg = _color_from_name(cfg.colors.get("focus_bg", "cyan"), curses.COLOR_CYAN)
    curses.init_pair(1, fg, bg)
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(4, curses.COLOR_RED, curses.COLOR_BLACK)

    if not is_case_dir(case_path):
        selected = select_case_directory(stdscr, case_path)
        if selected is None:
            return
        case_path = selected

    if not state.no_foam:
        try:
            ensure_environment()
        except OpenFOAMError as exc:
            set_no_foam_mode(state, True, str(exc))

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
        show_message(stdscr, f"Unexpected error: {exc}")


def _screen_check(stdscr: Any, case_path: Path, state: AppState) -> Screen:
    state.transition(Screen.CHECK, action="check")
    _check_syntax_screen(stdscr, case_path, state)
    return Screen.MAIN_MENU


def _screen_tools(stdscr: Any, case_path: Path, state: AppState) -> Screen:
    state.transition(Screen.TOOLS, action="tools")
    tools_screen(stdscr, case_path)
    return Screen.MAIN_MENU


def _screen_diagnostics(stdscr: Any, case_path: Path, state: AppState) -> Screen:
    state.transition(Screen.DIAGNOSTICS, action="diagnostics")
    diagnostics_screen(stdscr, case_path)
    return Screen.MAIN_MENU


def _screen_search(stdscr: Any, case_path: Path, state: AppState) -> Screen:
    state.transition(Screen.SEARCH, action="search")
    _global_search_screen(stdscr, case_path, state)
    return Screen.MAIN_MENU


def _screen_editor(stdscr: Any, case_path: Path, state: AppState) -> Screen:
    state.transition(Screen.EDITOR, action="editor")
    _editor_screen(stdscr, case_path, state)
    return Screen.MAIN_MENU


def _screen_main_menu(stdscr: Any, case_path: Path, state: AppState) -> Screen | None:
    return _main_menu_screen(stdscr, case_path, state)


def _menu_scroll(current: int, scroll: int, stdscr: Any, total: int, header_rows: int) -> int:
    return menu_scroll(current, scroll, stdscr, total, header_rows)


def _select_case_directory(stdscr: Any, start_path: Path) -> Path | None:
    return select_case_directory(stdscr, start_path)


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

    adapter = CursesAdapter(stdscr)
    router = ScreenRouter(
        handlers={
            Screen.MAIN_MENU: _screen_main_menu,
            Screen.CHECK: _screen_check,
            Screen.TOOLS: _screen_tools,
            Screen.DIAGNOSTICS: _screen_diagnostics,
            Screen.SEARCH: _screen_search,
            Screen.EDITOR: _screen_editor,
        },
    )
    next_screen: Screen | None = Screen.MAIN_MENU
    while next_screen is not None:
        next_screen = router.dispatch(
            next_screen,
            adapter.stdscr,
            case_path,
            state,
        )


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
        "Clean case",
        "Config Manager",
        "Tools",
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
        status_line=_root_status_line(state),
        help_lines=main_menu_help(),
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
        return _clean_case_menu(stdscr, case_path, state)
    if choice == 5:
        return _config_manager_menu(stdscr, case_path, state, has_fzf)
    if choice == 6:
        tools_screen(stdscr, case_path)
        return Screen.MAIN_MENU
    return Screen.MAIN_MENU


def _select_case_file(
    stdscr: Any,
    case_path: Path,
    state: AppState,
    sections: dict[str, list[Path]],
) -> Path | None:
    section_names = [name for name, files in sections.items() if files]
    if not section_names:
        show_message(stdscr, "No OpenFOAM case files found in this case.")
        return None
    section_index = option_index(section_names, state.last_section)

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
            show_message(stdscr, f"No files found in section {section}.")
            continue

        file_labels = [f.relative_to(case_path).as_posix() for f in files]
        file_index = option_index(file_labels, state.last_file)
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
        show_message(stdscr, "No entries found in file.")
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
        show_message(stdscr, f"Failed to read entry: {exc}")
        return

    entry = Entry(key=full_key, value=value)
    validator, type_label = choose_validator(full_key, value)
    validator, type_label = detect_type_with_foamlib(
        file_path,
        full_key,
        validator,
        type_label,
    )

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


def _annotate_content(content: str, extra_warnings: list[str] | None = None) -> str:
    warnings = find_suspicious_lines(content)
    if extra_warnings:
        warnings.extend(extra_warnings)

    if not warnings:
        return content

    lines = content.splitlines()
    line_notes: dict[int, list[str]] = {}
    general_notes: list[str] = []
    for warning in warnings:
        if warning.startswith("Line "):
            try:
                prefix, rest = warning.split(":", 1)
                line_no = int(prefix.split()[1])
                note = rest.strip()
                if line_no >= 1:
                    line_notes.setdefault(line_no, []).append(note)
                    continue
            except (ValueError, IndexError):
                pass
        general_notes.append(warning)

    annotated_lines: list[str] = []
    inserted_general = False
    for idx, line in enumerate(lines, 1):
        if not inserted_general and general_notes and line.strip():
            annotated_lines.extend(f"// LINT: {note}" for note in general_notes)
            inserted_general = True
        notes = line_notes.get(idx)
        if notes:
            note_text = " | ".join(notes)
            annotated_lines.append(f"{line}  // LINT: {note_text}")
        else:
            annotated_lines.append(line)

    if general_notes and not inserted_general:
        annotated_lines.extend(f"// LINT: {note}" for note in general_notes)

    return "\n".join(annotated_lines)


def _view_file_screen(
    stdscr: Any, file_path: Path, lint_warnings: list[str] | None = None,
) -> None:
    try:
        content = file_path.read_text()
    except OSError as exc:
        show_message(stdscr, f"Failed to read file: {exc}")
        return

    annotated = _annotate_content(content, extra_warnings=lint_warnings)
    viewer = Viewer(stdscr, annotated)
    viewer.display()



def _tasks_screen(stdscr: Any, state: AppState) -> None:
    tasks = state.tasks.list_tasks()
    if not tasks:
        show_message(stdscr, "No background tasks running.")
        return
    lines = ["Background tasks:"]
    for task in sorted(tasks, key=lambda item: item.name):
        message = f" - {task.message}" if task.message else ""
        lines.append(f"{task.name}: {task.status}{message}")
    lines.append("")
    lines.append("Use :cancel <task-name> to stop a task.")
    viewer = Viewer(stdscr, "\n".join(lines))
    viewer.display()




def _command_callbacks() -> CommandCallbacks:
    return CommandCallbacks(
        check_syntax=_check_syntax_screen,
        tools_screen=tools_screen,
        diagnostics_screen=diagnostics_screen,
        run_current_solver=run_current_solver,
        show_message=show_message,
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
        show_message=show_message,
        view_file=_view_file_screen,
        prompt_command=prompt_command,
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
    reason = f" [{state.no_foam_reason}]" if state.no_foam and state.no_foam_reason else ""
    return f"mode: {mode}{suffix}{reason}"


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
        show_message(stdscr, "No case files found to check.")
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
                show_message(
                    stdscr,
                    "Check syntax menu\n\n"
                    f"Enter: view result, {back_hint}: back\n\n"
                    "Includes required-entries linter. Progress is shown in the status bar.",
                )
            elif key_in(key, cfg.keys.get("command", [])):
                callbacks = _command_callbacks()
                command = prompt_command(stdscr, command_suggestions(case_path))
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
                    show_message(stdscr, f"{rel} not checked yet.")
                    continue
                if _show_check_result(stdscr, rel, check):
                    _view_file_screen(stdscr, file_path, lint_warnings=check.warnings)

            scroll = menu_scroll(current, scroll, stdscr, len(labels), header_rows=3)
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
    help_lines: list[str] | None = None,
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
        help_lines=help_lines,
    )
    choice = menu.navigate()
    if choice >= 0:
        state.menu_selection[menu_key] = choice
    return choice


def _root_status_line(state: AppState) -> str | None:
    parts: list[str] = []
    if state.no_foam:
        parts.append("Limited mode: OpenFOAM env not found (simple editor only)")
    if not foamlib_available():
        parts.append("foamlib: off")
    return " | ".join(parts) if parts else None


def _preprocessing_menu(stdscr: Any, case_path: Path, state: AppState) -> Screen:
    options = [
        "Run blockMesh",
        "blockMesh helper (vertices)",
        "Mesh quality (checkMesh)",
        "snappyHexMesh (staged run)",
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
            help_lines=preprocessing_help(),
        )
        if choice in (-1, len(options) - 1):
            return Screen.MAIN_MENU
        if choice == 0:
            run_tool_by_name(stdscr, case_path, "blockMesh")
        elif choice == 1:
            blockmesh_helper_screen(stdscr, case_path)
        elif choice == 2:
            run_checkmesh(stdscr, case_path)
        elif choice == 3:
            run_snappy = snappy_staged_screen(stdscr, case_path)
            if run_snappy:
                run_tool_by_name(stdscr, case_path, "snappyHexMesh")
        elif choice == 4:
            run_tool_by_name(stdscr, case_path, "decomposePar")
        elif choice == 5:
            reconstruct_manager_screen(stdscr, case_path)


def _physics_menu(stdscr: Any, case_path: Path, state: AppState) -> Screen:
    options = [
        "Config Editor",
        "Boundary matrix",
        "Thermophysical wizard",
        "High-speed initial conditions",
        "Check syntax",
        "Back",
    ]
    disabled = None
    if state.no_foam and not foamlib_available():
        disabled = {1, 2, 3, 4}
    while True:
        choice = _menu_choice(
            stdscr,
            "Physics & Boundary Conditions",
            options,
            state,
            "menu:physics",
            disabled_indices=disabled,
            help_lines=physics_help(),
        )
        if choice in (-1, len(options) - 1):
            return Screen.MAIN_MENU
        if choice == 0:
            _editor_screen(stdscr, case_path, state)
        elif choice == 1:
            boundary_matrix_screen(stdscr, case_path)
        elif choice == 2:
            thermophysical_wizard_screen(stdscr, case_path)
        elif choice == 3:
            high_speed_helper_screen(stdscr, case_path)
        elif choice == 4:
            _check_syntax_screen(stdscr, case_path, state)


def _simulation_menu(stdscr: Any, case_path: Path, state: AppState) -> Screen:
    options = [
        "Run current solver",
        "Run solver (live)",
        "Safe stop (create stop file)",
        "Resume solver (latestTime)",
        "foamJob (run job)",
        "foamEndJob (stop job)",
        "Job status (poll)",
        "Foamlib parametric study",
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
            help_lines=simulation_help(),
        )
        if choice in (-1, len(options) - 1):
            return Screen.MAIN_MENU
        if choice == 0:
            run_current_solver(stdscr, case_path)
        elif choice == 1:
            run_current_solver_live(stdscr, case_path)
        elif choice == 2:
            safe_stop_screen(stdscr, case_path)
        elif choice == 3:
            solver_resurrection_screen(stdscr, case_path)
        elif choice == 4:
            run_tool_by_name(stdscr, case_path, "foamJob")
        elif choice == 5:
            run_tool_by_name(stdscr, case_path, "foamEndJob")
        elif choice == 6:
            run_tool_by_name(stdscr, case_path, "jobStatus")
        elif choice == 7:
            foamlib_parametric_study_screen(stdscr, case_path)


def _postprocessing_menu(stdscr: Any, case_path: Path, state: AppState) -> Screen:
    options = [
        "Reconstruct manager",
        "Time directory pruner",
        "Tail log (highlight)",
        "View logs",
        "Residual timeline (foamlib)",
        "Probes viewer",
        "yPlus estimator",
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
            help_lines=postprocessing_help(),
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
            residual_timeline_screen(stdscr, case_path)
        elif choice == 5:
            probes_viewer_screen(stdscr, case_path)
        elif choice == 6:
            yplus_screen(stdscr, case_path)
        elif choice == 7:
            run_tool_by_name(stdscr, case_path, "postProcess")
        elif choice == 8:
            run_tool_by_name(stdscr, case_path, "foamCalc")
        elif choice == 9:
            run_tool_by_name(stdscr, case_path, "runScript")


def _config_manager_menu(
    stdscr: Any, case_path: Path, state: AppState, has_fzf: bool,
) -> Screen:
    options = [
        "Config Editor",
        "Create missing config",
        "OpenFOAM environment",
        "Check syntax",
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
                disabled = set()
                if not foamlib_available():
                    disabled.add(3)
                if has_fzf:
                    disabled.add(4)
            choice = _menu_choice(
                stdscr,
                "Config Manager",
                options,
                state,
                "menu:config",
                disabled_indices=disabled,
                help_lines=config_help(),
            )
            if choice in (-1, len(options) - 1):
                return Screen.MAIN_MENU
            if choice == 0:
                _editor_screen(stdscr, case_path, state)
            elif choice == 1:
                _create_missing_config_screen(stdscr, case_path)
            elif choice == 2:
                openfoam_env_screen(stdscr)
            elif choice == 3:
                _check_syntax_screen(stdscr, case_path, state)
            elif has_fzf and choice == 4:
                _global_search_screen(stdscr, case_path, state)
    finally:
        cfg.keys["search"] = original_search


def _create_missing_config_screen(stdscr: Any, case_path: Path) -> None:
    items = _missing_config_templates(case_path)
    if not items:
        show_message(stdscr, "All common config files exist.")
        return
    labels = [f"{label}: {path.relative_to(case_path)}" for label, path, _ in items]
    menu = Menu(stdscr, "Create missing config", [*labels, "Back"])
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return
    label, path, object_name = items[choice]
    _write_config_stub(path, object_name)
    show_message(stdscr, f"Created {label} at {path.relative_to(case_path)}.")


def _missing_config_templates(case_path: Path) -> list[tuple[str, Path, str]]:
    templates = [
        ("controlDict", case_path / "system" / "controlDict", "controlDict"),
        ("fvSchemes", case_path / "system" / "fvSchemes", "fvSchemes"),
        ("fvSolution", case_path / "system" / "fvSolution", "fvSolution"),
        ("decomposeParDict", case_path / "system" / "decomposeParDict", "decomposeParDict"),
        ("blockMeshDict", case_path / "system" / "blockMeshDict", "blockMeshDict"),
        ("snappyHexMeshDict", case_path / "system" / "snappyHexMeshDict", "snappyHexMeshDict"),
        ("transportProperties", case_path / get_dict_path("transport"), "transportProperties"),
        ("turbulenceProperties", case_path / get_dict_path("turbulence"), "turbulenceProperties"),
        (
            "thermophysicalProperties",
            case_path / get_dict_path("thermophysical"),
            "thermophysicalProperties",
        ),
    ]
    missing: list[tuple[str, Path, str]] = []
    for label, path, obj in templates:
        if not path.is_file():
            missing.append((label, path, obj))
    return missing


def _write_config_stub(path: Path, object_name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    template = [
        "/*--------------------------------*- C++ -*----------------------------------*\\",
        f"| OpenFOAM {object_name} dictionary (stub)                        |",
        "\\*---------------------------------------------------------------------------*/",
        "FoamFile",
        "{",
        "    version     2.0;",
        "    format      ascii;",
        "    class       dictionary;",
        f"    object      {object_name};",
        "}",
        "",
        "// TODO: fill in configuration.",
        "",
    ]
    path.write_text("\n".join(template))


def _clean_case_menu(stdscr: Any, case_path: Path, state: AppState) -> Screen:
    options = [
        "Remove all logs",
        "Clean time directories",
        "Clean case (logs + time dirs)",
        "Clean all (logs + time dirs + reconstruct)",
        "Time directory pruner",
        "Back",
    ]
    disabled = set(range(len(options) - 1)) if state.no_foam else None
    while True:
        choice = _menu_choice(
            stdscr,
            "Clean case",
            options,
            state,
            "menu:clean",
            disabled_indices=disabled,
            help_lines=clean_case_help(),
        )
        if choice in (-1, len(options) - 1):
            return Screen.MAIN_MENU
        if choice == 0:
            remove_all_logs(stdscr, case_path)
        elif choice == 1:
            clean_time_directories(stdscr, case_path)
        elif choice == 2:
            clean_case(stdscr, case_path)
        elif choice == 3:
            _clean_all(stdscr, case_path)
        elif choice == 4:
            time_directory_pruner_screen(stdscr, case_path)


def _show_progress(stdscr: Any, message: str) -> None:
    stdscr.clear()
    with suppress(curses.error):
        stdscr.addstr(message + "\n")
    stdscr.refresh()


def _clean_all(stdscr: Any, case_path: Path) -> None:
    remove_all_logs(stdscr, case_path)
    clean_time_directories(stdscr, case_path)
    reconstruct_manager_screen(stdscr, case_path)


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
            stdscr.addstr("Warnings are shown inline in the file view.\n\n")
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
        show_message(stdscr, "fzf not available (disabled or missing).")
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
                    show_message(
                        stdscr,
                        f"Global search failed: {exc} (no-foam mode may disable OpenFOAM tools)",
                    )
                    return
                continue
            entries.extend(EntryRef(dict_file, key) for key in keys)

    if not entries:
        show_message(stdscr, "No entries found for global search.")
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
            show_message(stdscr, "fzf not found.")
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
        show_message(stdscr, f"Failed to load keys for {rel_str}: {exc}")
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
        show_message(stdscr, f"Failed to run {editor}: {exc}")
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

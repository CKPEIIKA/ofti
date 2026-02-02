from __future__ import annotations

import curses
from pathlib import Path
from typing import Any

from ofti.app.commands import CommandCallbacks, command_suggestions, handle_command
from ofti.app.helpers import menu_scroll, prompt_command, show_message
from ofti.app.screens.editor import view_file_screen
from ofti.app.state import AppState
from ofti.app.status import mode_status, status_with_check
from ofti.core.entry_io import read_entry, write_entry
from ofti.core.templates import find_example_file
from ofti.foam.config import get_config, key_hint, key_in
from ofti.foam.openfoam import FileCheckResult, OpenFOAMError, discover_case_files, verify_case
from ofti.foam.tasks import Task
from ofti.ui_curses.layout import draw_status_bar, status_message


def start_check_thread(case_path: Path, state: AppState) -> None:
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


def check_syntax_screen(
    stdscr: Any,
    case_path: Path,
    state: AppState,
    *,
    command_callbacks: CommandCallbacks,
) -> None:
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
        check_syntax_menu(stdscr, case_path, state, command_callbacks=command_callbacks)
        return

    if state.check_results is None and not state.check_in_progress:
        start_check_thread(case_path, state)

    check_syntax_menu(stdscr, case_path, state, command_callbacks=command_callbacks)


def check_syntax_menu(
    stdscr: Any,
    case_path: Path,
    state: AppState,
    *,
    command_callbacks: CommandCallbacks,
) -> None:
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
            labels, checks = check_labels(case_path, files, state)
            status = status_with_check(state, "Check syntax")
            status = f"{status} | {mode_status(state)}" if status else mode_status(state)
            draw_check_menu(stdscr, labels, checks, current, scroll, status)
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
                command = prompt_command(stdscr, command_suggestions(case_path))
                if command and handle_command(
                    stdscr,
                    case_path,
                    state,
                    command,
                    command_callbacks,
                ) == "quit":
                    return
            elif key_in(key, cfg.keys.get("select", [])):
                file_path = files[current]
                check = checks[current]
                rel = file_path.relative_to(case_path)
                if check is None or not check.checked:
                    show_message(stdscr, f"{rel} not checked yet.")
                    continue
                if show_check_result(stdscr, file_path, rel, check):
                    view_file_screen(stdscr, file_path, lint_warnings=check.warnings)

            scroll = menu_scroll(current, scroll, stdscr, len(labels), header_rows=3)
    finally:
        stdscr.timeout(-1)


def check_labels(
    case_path: Path,
    files: list[Path],
    state: AppState,
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


def draw_check_menu(
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
        has_errors = bool(check and check.errors)
        has_warnings = bool(check and check.warnings)
        try:
            if has_errors:
                stdscr.attron(curses.color_pair(4))
                stdscr.attron(curses.A_BOLD)
            elif has_warnings:
                stdscr.attron(curses.color_pair(3))
                stdscr.attron(curses.A_BOLD)
            elif is_checked:
                stdscr.attron(curses.color_pair(2))
                stdscr.attron(curses.A_BOLD)
            else:
                stdscr.attron(curses.A_DIM)
            stdscr.addstr(start_row + (idx - scroll), 0, line[: max(1, width - 1)])
            if has_errors:
                stdscr.attroff(curses.A_BOLD)
                stdscr.attroff(curses.color_pair(4))
            elif has_warnings:
                stdscr.attroff(curses.A_BOLD)
                stdscr.attroff(curses.color_pair(3))
            elif is_checked:
                stdscr.attroff(curses.A_BOLD)
                stdscr.attroff(curses.color_pair(2))
            else:
                stdscr.attroff(curses.A_DIM)
        except curses.error:
            break

    draw_status_bar(stdscr, status)


def show_check_result(
    stdscr: Any,
    file_path: Path,
    rel_path: Path,
    result: FileCheckResult,
) -> bool:
    status = "OK"
    if not result.checked:
        status = "NOT CHECKED"
    elif result.errors:
        status = "ERROR"
    elif result.warnings:
        status = "Warnings"

    while True:
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
            fix_hint = "f"
            stdscr.addstr(
                f"Press {view_hint} to view file, {fix_hint} to auto-fix, "
                f"or {back_hint} to return.\n",
            )
            stdscr.refresh()
        except curses.error:
            stdscr.refresh()

        ch = stdscr.getch()
        if key_in(ch, get_config().keys.get("view", [])):
            return True
        if key_in(ch, get_config().keys.get("back", [])):
            return False
        if ch in (ord("f"), ord("F")):
            auto_fix_missing_required_entries(stdscr, file_path, rel_path, result)
            return False


def auto_fix_missing_required_entries(
    stdscr: Any,
    file_path: Path,
    rel_path: Path,
    result: FileCheckResult,
) -> None:
    if not result.errors:
        show_message(stdscr, "No missing required entries detected.")
        return
    missing_map: dict[str, list[str]] = {}
    for item in result.errors:
        if "missing required entries:" not in item:
            continue
        prefix, rest = item.split("missing required entries:", 1)
        key = prefix.strip().rstrip(":")
        missing = [part.strip() for part in rest.split(",") if part.strip()]
        if missing:
            missing_map[key] = missing
    if not missing_map:
        show_message(stdscr, "No missing required entries detected.")
        return

    example_path = find_example_file(rel_path)
    if example_path is None:
        show_message(stdscr, "No example template found to auto-fix this file.")
        return

    fixed: list[str] = []
    skipped: list[str] = []
    for key, missing_keys in missing_map.items():
        for missing_key in missing_keys:
            full_key = f"{key}.{missing_key}" if key else missing_key
            try:
                value = read_entry(example_path, full_key)
            except OpenFOAMError:
                skipped.append(full_key)
                continue
            ok = write_entry(file_path, full_key, value)
            if ok:
                fixed.append(full_key)
            else:
                skipped.append(full_key)

    if fixed:
        show_message(
            stdscr,
            "Inserted entries:\n" + "\n".join(f"- {item}" for item in fixed),
        )
        return
    if skipped:
        show_message(
            stdscr,
            "No entries inserted. Missing example values for:\n"
            + "\n".join(f"- {item}" for item in skipped),
        )
        return
    show_message(stdscr, "No entries inserted.")

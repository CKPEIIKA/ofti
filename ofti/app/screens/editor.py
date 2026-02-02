from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from ofti.app.commands import CommandCallbacks, command_suggestions, handle_command
from ofti.app.helpers import option_index, show_message
from ofti.app.state import AppState, Screen
from ofti.core.entries import Entry, autoformat_value
from ofti.core.entry_io import list_keywords, list_subkeys, read_entry, write_entry
from ofti.core.entry_meta import choose_validator, detect_type_with_foamlib
from ofti.core.syntax import find_suspicious_lines
from ofti.foam.config import key_hint
from ofti.foam.openfoam import OpenFOAMError
from ofti.ui_curses.entry_browser import BrowserCallbacks, entry_browser_screen
from ofti.ui_curses.entry_editor import EntryEditor
from ofti.ui_curses.menus import Menu, Submenu
from ofti.ui_curses.viewer import Viewer


def editor_screen(
    stdscr: Any,
    case_path: Path,
    state: AppState,
    *,
    command_callbacks: CommandCallbacks,
    browser_callbacks: BrowserCallbacks,
) -> None:
    sections = simple_case_sections(case_path)
    while True:
        state.transition(Screen.EDITOR)
        file_path = select_case_file(stdscr, case_path, state, sections, command_callbacks)
        if file_path is None:
            return
        state.transition(Screen.ENTRY_BROWSER, action="entry_browser")
        entry_browser_screen(
            stdscr,
            case_path,
            file_path,
            state,
            browser_callbacks,
        )


def simple_case_sections(case_path: Path) -> dict[str, list[Path]]:
    """Noice-style case crawl: scan only top-level files in system/constant/0*."""
    sections: dict[str, list[Path]] = {}

    def add_section(name: str, folder: Path) -> None:
        entries = scan_dir_files(folder)
        if entries:
            sections[name] = entries

    add_section("system", case_path / "system")
    add_section("constant", case_path / "constant")

    for zero_dir in scan_zero_dirs(case_path):
        add_section(zero_dir.name, zero_dir)

    return sections


def scan_dir_files(folder: Path) -> list[Path]:
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


def scan_zero_dirs(case_path: Path) -> list[Path]:
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


def select_case_file(
    stdscr: Any,
    case_path: Path,
    state: AppState,
    sections: dict[str, list[Path]],
    command_callbacks: CommandCallbacks,
) -> Path | None:
    section_names = [name for name, files in sections.items() if files]
    if not section_names:
        show_message(stdscr, "No OpenFOAM case files found in this case.")
        return None
    section_index = option_index(section_names, state.last_section)

    while True:
        section_menu = Menu(
            stdscr,
            "Editor - select section",
            [*section_names, "Back"],
            initial_index=section_index,
            command_handler=lambda cmd, cb=command_callbacks: handle_command(
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
            file_menu = Menu(
                stdscr,
                f"{section} files",
                [*file_labels, "Back"],
                initial_index=file_index,
                command_handler=lambda cmd, cb=command_callbacks: handle_command(
                    stdscr, case_path, state, cmd, cb,
                ),
                command_suggestions=lambda: command_suggestions(case_path),
            )
            file_index = file_menu.navigate()
            if file_index == -1 or file_index == len(file_labels):
                break
            state.last_file = file_labels[file_index]
            return files[file_index]


def file_screen(
    stdscr: Any,
    case_path: Path,
    file_path: Path,
    state: AppState,
    command_callbacks: CommandCallbacks,
) -> None:
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
    submenu = Submenu(
        stdscr,
        f"{file_path.relative_to(case_path)}",
        options[:-1],
        command_handler=lambda cmd: handle_command(
            stdscr, case_path, state, cmd, command_callbacks,
        ),
        command_suggestions=lambda: command_suggestions(case_path),
    )
    while True:
        choice = submenu.navigate()
        if choice == -1 or choice == len(options) - 1:
            return
        if choice == 0:
            edit_entry_screen(
                stdscr,
                case_path,
                file_path,
                keywords,
                state,
                command_callbacks,
            )
        elif choice == 1:
            view_file_screen(stdscr, file_path)


def no_foam_file_screen(
    stdscr: Any,
    case_path: Path,
    file_path: Path,
    state: AppState,
    command_callbacks: CommandCallbacks,
) -> None:
    options = ["View file", "Open in $EDITOR", "Back"]
    while True:
        menu = Menu(
            stdscr,
            f"{file_path.relative_to(case_path)}",
            options,
            command_handler=lambda cmd: handle_command(
                stdscr, case_path, state, cmd, command_callbacks,
            ),
            command_suggestions=lambda: command_suggestions(case_path),
        )
        choice = menu.navigate()
        if choice == -1 or choice == len(options) - 1:
            return
        if choice == 0:
            view_file_screen(stdscr, file_path)
        elif choice == 1:
            open_file_in_editor(stdscr, file_path)


def edit_entry_screen(
    stdscr: Any,
    case_path: Path,
    file_path: Path,
    keywords: list[str],
    state: AppState,
    command_callbacks: CommandCallbacks,
    *,
    base_entry: str | None = None,
) -> None:
    if not keywords:
        show_message(stdscr, "No entries found in file.")
        return

    entry_menu = Menu(
        stdscr,
        "Select entry to edit",
        [*keywords, "Back"],
        command_handler=lambda cmd: handle_command(
            stdscr, case_path, state, cmd, command_callbacks,
        ),
        command_suggestions=lambda: command_suggestions(case_path),
    )
    entry_index = entry_menu.navigate()
    if entry_index == -1 or entry_index == len(keywords):
        return

    key = keywords[entry_index]
    full_key = key if base_entry is None else f"{base_entry}.{key}"

    subkeys = list_subkeys(file_path, full_key)
    if subkeys:
        submenu = Menu(
            stdscr,
            f"{full_key} is a dictionary",
            ["Browse sub-entries", "Edit this entry", "Back"],
            command_handler=lambda cmd: handle_command(
                stdscr, case_path, state, cmd, command_callbacks,
            ),
            command_suggestions=lambda: command_suggestions(case_path),
        )
        choice = submenu.navigate()
        if choice == 0:
            edit_entry_screen(
                stdscr,
                case_path,
                file_path,
                subkeys,
                state,
                command_callbacks,
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
    )
    editor.display()


def _annotate_content(content: str, extra_warnings: list[str] | None = None) -> str:
    warnings = find_suspicious_lines(content)
    if extra_warnings:
        warnings = [*warnings, *extra_warnings]
    if not warnings:
        return content

    lines = content.splitlines()
    notes: dict[int, list[str]] = {}
    general_notes: list[str] = []
    for warning in warnings:
        if warning.line is None:
            general_notes.append(warning.message)
        else:
            notes.setdefault(warning.line, []).append(warning.message)

    annotated_lines: list[str] = []
    inserted_general = False
    for idx, line in enumerate(lines, start=1):
        if idx in notes:
            note_text = " | ".join(notes[idx])
            annotated_lines.append(f"{line}  // LINT: {note_text}")
        else:
            annotated_lines.append(line)

    if general_notes and not inserted_general:
        annotated_lines.extend(f"// LINT: {note}" for note in general_notes)

    return "\n".join(annotated_lines)


def view_file_screen(
    stdscr: Any,
    file_path: Path,
    lint_warnings: list[str] | None = None,
) -> None:
    try:
        content = file_path.read_text()
    except OSError as exc:
        show_message(stdscr, f"Failed to read file: {exc}")
        return

    annotated = _annotate_content(content, extra_warnings=lint_warnings)
    viewer = Viewer(stdscr, annotated)
    viewer.display()


def open_file_in_editor(stdscr: Any, file_path: Path) -> None:
    editor = os.environ.get("EDITOR")
    if not editor:
        show_message(stdscr, "EDITOR is not set.")
        return

    try:
        subprocess.run([editor, str(file_path)], check=False)  # noqa: S603
    except OSError as exc:
        show_message(stdscr, f"Failed to open editor: {exc}")

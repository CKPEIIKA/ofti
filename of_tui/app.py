import curses
import logging
import os
import re
import shutil
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import List, Any

from .editor import Entry, EntryEditor, Viewer
from .domain import DictionaryFile, EntryRef, Case
from .menus import Menu, RootMenu, Submenu
from .tools import tools_screen, diagnostics_screen
from .openfoam import (
    FileCheckResult,
    OpenFOAMError,
    discover_case_files,
    ensure_environment,
    get_entry_comments,
    get_entry_info,
    get_entry_enum_values,
    list_keywords,
    list_subkeys,
    read_entry,
    verify_case,
    write_entry,
)
from .validation import (
    Validator,
    as_float,
    as_int,
    bool_flag,
    non_empty,
    vector_values,
)


def run_tui(case_dir: str, debug: bool = False) -> None:
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
    curses.wrapper(_main, case_path, debug)


def _main(stdscr: Any, case_path: Path, debug: bool) -> None:
    curses.start_color()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)

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
        _main_loop(stdscr, case_path)
    except KeyboardInterrupt:
        # Clean, user-initiated exit with restored terminal state.
        return
    except Exception as exc:  # pragma: no cover - defensive safety net
        if debug:
            # Re-raise to get a full traceback in debug mode.
            raise
        _show_message(stdscr, f"Unexpected error: {exc}")


def _main_loop(stdscr: Any, case_path: Path) -> None:

    foam_case = Case(root=case_path)
    sections = discover_case_files(foam_case.root)
    section_names = [name for name, files in sections.items() if files]
    if not section_names:
        stdscr.addstr("No OpenFOAM case files found.\n")
        stdscr.addstr("Press any key to exit.\n")
        stdscr.refresh()
        stdscr.getch()
        return

    while True:
        has_fzf = shutil.which("fzf") is not None

        menu_options = [
            "Editor",
            "Check syntax",
            "Tools",
            "Diagnostics",
        ]
        editor_index = 0
        check_index = 1
        tools_index = 2
        diag_index = 3

        search_index: int | None = None
        if has_fzf:
            search_index = len(menu_options)
            menu_options.append("Global search")

        quit_index = len(menu_options)
        menu_options.append("Quit")

        case_meta = _case_metadata(case_path)
        banner_lines = _case_banner_lines(case_meta)
        overview_lines = _case_overview_lines(case_meta)
        root_menu = RootMenu(
            stdscr,
            "Main menu",
            menu_options,
            extra_lines=overview_lines,
            banner_lines=banner_lines,
        )
        choice = root_menu.navigate()
        if choice == -1 or choice == quit_index:
            return
        if choice == check_index:
            _check_syntax_screen(stdscr, case_path)
            continue
        if choice == tools_index:
            tools_screen(stdscr, case_path)
            continue
        if choice == diag_index:
            diagnostics_screen(stdscr, case_path)
            continue
        if search_index is not None and choice == search_index:
            _global_search_screen(stdscr, case_path)
            continue

        # Editor: choose section (system, constant, 0*, ...)
        _editor_screen(stdscr, case_path)


def _editor_screen(stdscr: Any, case_path: Path) -> None:
    sections = discover_case_files(case_path)
    section_names = [name for name, files in sections.items() if files]
    if not section_names:
        _show_message(stdscr, "No OpenFOAM case files found in this case.")
        return

    while True:
        section_menu = Menu(stdscr, "Editor – select section", section_names + ["Back"])
        section_index = section_menu.navigate()
        if section_index == -1 or section_index == len(section_names):
            return

        section = section_names[section_index]
        files = sections.get(section, [])
        if not files:
            _show_message(stdscr, f"No files found in section {section}.")
            continue

        file_labels = [f.relative_to(case_path).as_posix() for f in files]
        while True:
            file_menu = Menu(stdscr, f"{section} files", file_labels + ["Back"])
            file_index = file_menu.navigate()
            if file_index == -1 or file_index == len(file_labels):
                break
            file_path = files[file_index]
            _entry_browser_screen(stdscr, case_path, file_path)


def _file_screen(stdscr: Any, case_path: Path, file_path: Path) -> None:
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
    submenu = Submenu(stdscr, f"{file_path.relative_to(case_path)}", options[:-1])
    while True:
        choice = submenu.navigate()
        if choice == -1 or choice == len(options) - 1:
            return
        if choice == 0:
            _edit_entry_screen(stdscr, file_path, keywords)
        elif choice == 1:
            _view_file_screen(stdscr, file_path)


def _entry_browser_screen(
    stdscr: Any, case_path: Path, file_path: Path, initial_index: int | None = None
) -> None:
    """
    Browse entries in a file with a left-hand list and right-hand preview.

    Keys:
      j/k or arrows : move between entries
      l or Enter    : drill into sub-dicts or edit entry
      h or q        : go back (or up one dict level)
      v             : view entire file
    """
    base_entry: str | None = None
    stack: list[tuple[str | None, list[str], int]] = []
    cache: dict[str, tuple[str, str, list[str], list[str], list[str]]] = {}

    try:
        keywords = list_keywords(file_path)
    except OpenFOAMError as exc:
        _show_message(stdscr, f"Error reading {file_path.relative_to(case_path)}: {exc}")
        return

    if not keywords:
        _show_message(stdscr, "No entries found in file.")
        return

    index = 0 if initial_index is None else max(0, min(initial_index, len(keywords) - 1))

    while True:
        # Determine current key path and preview info (using a simple cache
        # so moving over values does not repeatedly hit foamDictionary).
        key = keywords[index]
        full_key = key if base_entry is None else f"{base_entry}.{key}"

        value, type_label, subkeys, comments, info_lines, validator = _get_entry_metadata(
            cache, file_path, case_path, full_key
        )

        _draw_entry_browser(
            stdscr,
            case_path,
            file_path,
            base_entry,
            keywords,
            index,
            full_key,
            value,
            type_label,
            subkeys,
            comments,
            info_lines,
        )

        key_code = stdscr.getch()

        if key_code in (ord("k"), curses.KEY_UP):
            index = (index - 1) % len(keywords)
        elif key_code in (ord("j"), curses.KEY_DOWN):
            index = (index + 1) % len(keywords)
        elif key_code in (ord("h"), curses.KEY_LEFT, ord("q")):
            if stack:
                base_entry, keywords, index = stack.pop()
            else:
                return
        elif key_code == ord("o"):
            # Open the current entry in an external editor ($EDITOR) and
            # write back whatever the user saves.
            try:
                original_value = read_entry(file_path, full_key)
            except OpenFOAMError as exc:
                _show_message(stdscr, f"Failed to read entry for editor: {exc}")
                continue

            edited_value = _open_in_external_editor(stdscr, original_value)
            if edited_value is None or edited_value == original_value:
                continue

            formatted = _autoformat_value(edited_value)
            if not write_entry(file_path, full_key, formatted):
                _show_message(stdscr, "Failed to save value from editor.")
                continue

            # Refresh cached value after external edit.
            _refresh_entry_cache(cache, file_path, case_path, full_key)
        elif key_code == ord("v"):
            _view_file_screen(stdscr, file_path)
        elif key_code in (
            ord("l"),
            ord("e"),
            curses.KEY_RIGHT,
            ord("\n"),
            curses.KEY_ENTER,
        ):
            # Drill into dict or edit value.
            if subkeys:
                stack.append((base_entry, keywords, index))
                base_entry = full_key
                keywords = subkeys
                index = 0
                continue

            # No subkeys: edit this entry in place.
            entry = Entry(key=full_key, value=value)

            def on_save(new_value: str) -> bool:
                formatted = _autoformat_value(new_value)
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

            # After editing, refresh cache from disk so that the browser
            # reflects the actual saved value (if write succeeded).
            _refresh_entry_cache(cache, file_path, case_path, full_key)
        elif key_code == curses.KEY_RESIZE:
            # Screen will be fully redrawn on next loop iteration.
            continue
        elif key_code == ord("/"):
            # Prefer fzf-based search when available; fall back to simple
            # in-file search otherwise.
            if shutil.which("fzf") is not None:
                new_index = _fzf_pick_entry_in_file(stdscr, keywords)
                if new_index is not None:
                    index = new_index
            else:
                # Search keys, values, and comments in this file.
                curses.echo()
                stdscr.clear()
                stdscr.addstr("Search (keys/values/comments): ")
                stdscr.refresh()
                query = stdscr.getstr().decode()
                curses.noecho()
                if query:
                    new_index = _search_entries(
                        cache, file_path, case_path, keywords, index, query, direction=1
                    )
                    if new_index is None:
                        _show_message(stdscr, f"No matches for '{query}'.")
                    else:
                        index = new_index
            continue
        elif key_code == ord("?"):
            _show_message(
                stdscr,
                "j/k or arrows: move, l/e/Right/Enter: edit, h/Left/q: back, v: view file, /: search, ?: help",
            )


def _draw_entry_browser(
    stdscr: Any,
    case_path: Path,
    file_path: Path,
    base_entry: str | None,
    keys: list[str],
    current_index: int,
    full_key: str,
    value: str,
    type_label: str,
    subkeys: list[str],
    comments: list[str],
    info_lines: list[str],
) -> None:
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    split_col = max(20, width // 2)
    left_width = split_col - 1
    right_width = width - split_col - 1

    # Use dedicated windows for left/right panes; status bar stays on stdscr.
    try:
        left_win = stdscr.derwin(max(1, height - 1), split_col, 0, 0)
        right_win = stdscr.derwin(max(1, height - 1), max(1, width - split_col), 0, split_col)
    except curses.error:
        # Fallback: draw everything on stdscr if window creation fails.
        left_win = stdscr
        right_win = stdscr

    left_win.erase()
    right_win.erase()

    # Left pane: file + entries.
    try:
        file_label = file_path.relative_to(case_path).as_posix()
        left_win.addstr(0, 0, file_label[: max(1, left_width)])
        level_label = base_entry or "(top level)"
        left_win.addstr(1, 0, level_label[: max(1, left_width)])
        left_win.addstr(
            2,
            0,
            "j/k: move  l: edit  o: edit section  v: view  h: back"[
                : max(1, left_width)
            ],
        )
    except curses.error:
        pass

    start_row = 4
    for idx, k in enumerate(keys):
        if start_row + idx >= height - 1:
            break
        prefix = ">> " if idx == current_index else "   "
        label = (prefix + k)[: max(1, left_width)]
        try:
            left_win.addstr(start_row + idx, 0, label)
        except curses.error:
            break

    # Right pane: preview of current entry and hierarchy.
    try:
        right_win.addstr(0, 0, "Entry preview"[: max(1, right_width)])
        # Show key hierarchy as dotted path.
        right_win.addstr(
            1,
            0,
            f"Path: {full_key}"[: max(1, right_width)],
        )
        right_win.addstr(
            2,
            0,
            f"Type: {type_label}"[: max(1, right_width)],
        )
    except curses.error:
        pass

    row = 4
    try:
        right_win.addstr(row, 0, "Current value:"[: max(1, right_width)])
    except curses.error:
        pass
    row += 1
    for line in value.splitlines() or [value]:
        if row >= height - 1:
            break
        try:
            right_win.addstr(row, 0, line[: max(1, right_width)])
        except curses.error:
            break
        row += 1

    # Comments (docs) if present.
    if comments and row < height - 1:
        try:
            right_win.addstr(row, 0, "Comments:"[: max(1, right_width)])
        except curses.error:
            pass
        row += 1
        for c in comments:
            if row >= height - 1:
                break
            try:
                right_win.addstr(
                    row,
                    0,
                    c[: max(1, right_width)],
                )
            except curses.error:
                break
            row += 1

    # Additional info from foamDictionary -info, if available.
    if info_lines and row < height - 1:
        try:
            right_win.addstr(row, 0, "Info:"[: max(1, right_width)])
        except curses.error:
            pass
        row += 1
        for line in info_lines:
            if row >= height - 1:
                break
            try:
                right_win.addstr(
                    row,
                    0,
                    line[: max(1, right_width)],
                )
            except curses.error:
                break
            row += 1

    # Sub-keys if this is a dictionary.
    if subkeys and row < height - 1:
        try:
            right_win.addstr(row, 0, "Sub-keys:"[: max(1, right_width)])
        except curses.error:
            pass
        row += 1
        for sk in subkeys:
            if row >= height - 1:
                break
            try:
                right_win.addstr(
                    row,
                    0,
                    f"- {sk}"[: max(1, right_width)],
                )
            except curses.error:
                break
            row += 1

    # Status bar with case and current path.
    _draw_status_bar(
        stdscr,
        f"case: {case_path.name} | file: {file_path.relative_to(case_path)} | path: {full_key}",
    )

    try:
        left_win.noutrefresh()
        right_win.noutrefresh()
        stdscr.noutrefresh()
        curses.doupdate()
    except curses.error:
        stdscr.refresh()


def _edit_entry_screen(
    stdscr: Any, file_path: Path, keywords: List[str], base_entry: str | None = None
) -> None:
    if not keywords:
        _show_message(stdscr, "No entries found in file.")
        return

    entry_menu = Menu(stdscr, "Select entry to edit", keywords + ["Back"])
    entry_index = entry_menu.navigate()
    if entry_index == -1 or entry_index == len(keywords):
        return

    key = keywords[entry_index]
    full_key = key if base_entry is None else f"{base_entry}.{key}"

    # If this entry has sub-keys, offer to browse deeper.
    subkeys = list_subkeys(file_path, full_key)
    if subkeys:
        # Submenu to choose between browsing sub-entries or editing this entry directly.
        submenu = Menu(
            stdscr,
            f"{full_key} is a dictionary",
            ["Browse sub-entries", "Edit this entry", "Back"],
        )
        choice = submenu.navigate()
        if choice == 0:
            _edit_entry_screen(stdscr, file_path, subkeys, base_entry=full_key)
            return
        if choice in (-1, 2):
            return

    try:
        value = read_entry(file_path, full_key)
    except OpenFOAMError as exc:
        _show_message(stdscr, f"Failed to read entry: {exc}")
        return

    entry = Entry(key=full_key, value=value)
    validator, type_label = _choose_validator(full_key, value)

    def on_save(new_value: str) -> bool:
        formatted = _autoformat_value(new_value)
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
        if stripped_line.endswith(";") or stripped_line.endswith("{") or stripped_line.endswith("}"):
            continue
        if stripped_line.endswith("(") or stripped_line.endswith(")"):
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


def _draw_status_bar(stdscr: Any, text: str) -> None:
    """
    Draw a simple status bar on the last line of the screen.
    """
    try:
        height, width = stdscr.getmaxyx()
        stdscr.attron(curses.A_REVERSE)
        stdscr.addstr(
            height - 1,
            0,
            text[: max(1, width - 1)].ljust(max(1, width - 1)),
        )
        stdscr.attroff(curses.A_REVERSE)
    except curses.error:
        pass


def _get_entry_metadata(
    cache: dict[str, tuple[str, str, list[str], list[str], list[str]]],
    file_path: Path,
    case_path: Path,
    full_key: str,
) -> tuple[str, str, list[str], list[str], list[str], Validator]:
    """
    Load entry metadata (value, type label, subkeys, comments, info_lines, validator),
    using a simple cache to avoid repeated foamDictionary calls while
    navigating.
    """
    if full_key in cache:
        value, type_label, subkeys, comments, info_lines = cache[full_key]
        validator, _ = _choose_validator(full_key, value)
        return value, type_label, subkeys, comments, info_lines, validator

    try:
        value = read_entry(file_path, full_key)
    except OpenFOAMError:
        value = "<error reading value>"

    validator, type_label = _choose_validator(full_key, value)
    subkeys = list_subkeys(file_path, full_key)
    comments = get_entry_comments(file_path, full_key)
    info_lines = get_entry_info(file_path, full_key)
    info_lines.extend(_boundary_condition_info(file_path, full_key))

    # If foamDictionary reports an explicit list of allowed values via
    # `-list`, prefer an enum-style validator over heuristics.
    enum_values = get_entry_enum_values(file_path, full_key)
    if enum_values:
        allowed_set = set(enum_values)

        def enum_validator(v: str) -> str | None:
            text = v.strip().rstrip(";").strip()
            if text in allowed_set:
                return None
            return f"Value must be one of: {', '.join(sorted(allowed_set))}."

        validator = enum_validator
        type_label = "enum"
        # Surface allowed values in the info pane as well.
        info_lines = info_lines + [f"Allowed values: {', '.join(enum_values)}"]

    cache[full_key] = (value, type_label, subkeys, comments, info_lines)
    return value, type_label, subkeys, comments, info_lines, validator


def _refresh_entry_cache(
    cache: dict[str, tuple[str, str, list[str], list[str], list[str]]],
    file_path: Path,
    case_path: Path,
    full_key: str,
) -> None:
    """
    Refresh a single entry in the cache after an edit, swallowing
    OpenFOAM errors so the UI remains responsive.
    """
    try:
        value = read_entry(file_path, full_key)
    except OpenFOAMError:
        return

    validator, type_label = _choose_validator(full_key, value)
    subkeys = list_subkeys(file_path, full_key)
    comments = get_entry_comments(file_path, full_key)
    info_lines = get_entry_info(file_path, full_key)
    info_lines.extend(_boundary_condition_info(file_path, full_key))
    cache[full_key] = (value, type_label, subkeys, comments, info_lines)


def _autoformat_value(value: str) -> str:
    """
    Apply a very small amount of auto-formatting before saving.

    - For single-line values, trim leading/trailing whitespace.
    - For multi-line values, leave content as-is (only strip trailing
      newlines) to avoid breaking complex dictionaries.
    """
    text = value.rstrip("\n")
    if "\n" in text:
        return text
    return text.strip()


def _search_entries(
    cache: dict[str, tuple[str, str, list[str], list[str], list[str]]],
    file_path: Path,
    case_path: Path,
    keywords: list[str],
    current_index: int,
    query: str,
    direction: int = 1,
) -> int | None:
    """
    Search forward or backward from current_index for an entry whose key,
    value, or comments contain the query (case-insensitive).
    Returns the index of the next match, or None if no match is found.
    """
    if not keywords:
        return None

    q = query.lower()

    n = len(keywords)
    for step in range(1, n + 1):
        idx = (current_index + direction * step) % n
        key = keywords[idx]
        full_key = key
        value, _type_label, _subkeys, comments, _info_lines, _validator = _get_entry_metadata(
            cache, file_path, case_path, full_key
        )
        haystack = " ".join([key, value] + comments).lower()
        if q in haystack:
            return idx

    return None


def _fzf_pick_entry_in_file(stdscr: Any, keywords: list[str]) -> int | None:
    """
    Use fzf to pick an entry from the current file (current directory
    context) based on its key. Returns the selected index or None if
    selection was cancelled.
    """
    if not keywords:
        return None

    fzf_input = "\n".join(keywords)

    # Temporarily suspend curses UI while running fzf.
    curses.def_prog_mode()
    curses.endwin()
    try:
        result = subprocess.run(
            ["fzf"],
            input=fzf_input,
            text=True,
            capture_output=True,
        )
    finally:
        # Restore curses mode and refresh the screen.
        curses.reset_prog_mode()
        stdscr.clear()
        stdscr.refresh()

    if result.returncode != 0:
        return None

    selected = result.stdout.strip()
    if not selected:
        return None

    try:
        return keywords.index(selected)
    except ValueError:
        return None


def _check_syntax_screen(stdscr: Any, case_path: Path) -> None:
    def progress_callback(path: Path) -> None:
        try:
            rel = path.relative_to(case_path)
        except ValueError:
            rel = path
        _show_progress(stdscr, f"Checking {rel} ...")

    _show_progress(stdscr, "Running foamDictionary checks...")
    results = verify_case(case_path, progress=progress_callback)
    if not results:
        _show_message(stdscr, "No case files found to check.")
        return

    entries = sorted(results.items(), key=lambda item: item[0])
    labels: list[str] = []
    for file_path, check in entries:
        rel = file_path.relative_to(case_path)
        if check.errors:
            status = f"ERROR ({len(check.errors)})"
        elif check.warnings:
            status = f"Warn ({len(check.warnings)})"
        else:
            status = "OK"
        labels.append(f"{rel}: {status}")

    menu = Menu(stdscr, "Check syntax – select file", labels + ["Back"])
    while True:
        choice = menu.navigate()
        if choice == -1 or choice == len(labels):
            return
        file_path, check = entries[choice]
        rel = file_path.relative_to(case_path)

        if _show_check_result(stdscr, rel, check):
            _view_file_screen(stdscr, file_path)


def _show_progress(stdscr: Any, message: str) -> None:
    stdscr.clear()
    try:
        stdscr.addstr(message + "\n")
    except curses.error:
        pass
    stdscr.refresh()


def _show_check_result(stdscr: Any, rel_path: Path, result: FileCheckResult) -> bool:
    status = "OK"
    if result.errors:
        status = "ERROR"
    elif result.warnings:
        status = "Warnings"

    stdscr.clear()
    line = f"{rel_path}: {status}"
    try:
        stdscr.addstr(line + "\n\n")
        if result.errors:
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


def _global_search_screen(stdscr: Any, case_path: Path) -> None:
    """
    Global search wrapper around `fzf`.

    Lists all dictionary entries (file + key + snippet), lets the user
    fuzzy-select one via `fzf`, and then opens the editor browser at
    the chosen entry as if it was selected manually.
    """
    if shutil.which("fzf") is None:
        _show_message(stdscr, "fzf not found on PATH. Please install fzf to use global search.")
        return

    foam_case = Case(root=case_path)
    sections = discover_case_files(foam_case.root)
    entries: list[EntryRef] = []

    for _section, files in sections.items():
        for file_path in files:
            dict_file = DictionaryFile(foam_case.root, file_path)
            try:
                keys = list_keywords(file_path)
            except OpenFOAMError:
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
    _entry_browser_screen(stdscr, case_path, file_path, initial_index=initial_index)


def _open_in_external_editor(stdscr: Any, initial_text: str) -> str | None:
    """
    Open the given text in $EDITOR and return the edited content.

    Returns None if the editor could not be launched.
    """
    editor = os.environ.get("EDITOR") or "vi"

    # Use a NamedTemporaryFile so the editor can work on a real file path.
    try:
        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(initial_text)
    except OSError as exc:
        _show_message(stdscr, f"Failed to create temp file for editor: {exc}")
        return None

    # Suspend curses UI while the external editor runs.
    curses.endwin()
    try:
        subprocess.run([editor, str(tmp_path)])
    finally:
        # Re-initialize the screen; next draw call will refresh the UI.
        stdscr.clear()
        stdscr.refresh()

    try:
        edited = tmp_path.read_text()
    except OSError as exc:
        _show_message(stdscr, f"Failed to read edited value: {exc}")
        return None
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    return edited


def _load_tool_presets(case_path: Path) -> list[tuple[str, list[str]]]:
    """
    Load extra tools from an optional per-case file `of_tui.tools`.

    Format (one per line, lines starting with # are ignored):
      name: command with args
    Example:
      simpleFoam: simpleFoam -case .
    """
    presets: list[tuple[str, list[str]]] = []
    cfg_path = case_path / "of_tui.tools"
    if not cfg_path.is_file():
        return presets

    try:
        for raw_line in cfg_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            name, cmd_str = line.split(":", 1)
            name = name.strip()
            cmd_str = cmd_str.strip()
            if not name or not cmd_str:
                continue
            try:
                cmd = shlex.split(cmd_str)
            except ValueError:
                continue
            presets.append((name, cmd))
    except OSError:
        return presets

    return presets


def _case_metadata(case_path: Path) -> dict[str, str]:
    return {
        "case_name": case_path.name,
        "case_path": str(case_path),
        "solver": _detect_solver(case_path),
        "foam_version": _detect_openfoam_version(),
        "case_header_version": _detect_case_header_version(case_path),
        "latest_time": _latest_time(case_path),
    }


def _case_overview_lines(meta: dict[str, str]) -> list[str]:
    # Additional summary lines below the banner; keep minimal to avoid clutter.
    return []


def _case_banner_lines(meta: dict[str, str]) -> list[str]:
    rows = [
        (f"Case: {meta['case_name']}", f"Solver: {meta['solver']}"),
        (f"Env: {meta['foam_version']}", f"Case header: {meta['case_header_version']}"),
        (f"Latest time: {meta['latest_time']}", f"Path: {meta['case_path']}"),
    ]
    return _foam_style_banner("of_tui", rows)


def _foam_style_banner(label: str, rows: list[tuple[str, str]]) -> list[str]:
    top = f"/*--------------------------------*- {label} -*----------------------------------*\\"
    bottom = "\\*---------------------------------------------------------------------------*/"
    lines = [top]
    for left, right in rows:
        lines.append(_format_banner_row(left, right))
    lines.append(bottom)
    return lines


def _format_banner_row(left: str, right: str, column_width: int = 36) -> str:
    def clip(text: str) -> str:
        return text[:column_width]

    return f"| {clip(left).ljust(column_width)} | {clip(right).ljust(column_width)} |"


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
        )
    except OSError:
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    version = result.stdout.strip()
    return version or "unknown"


def _detect_case_header_version(case_path: Path) -> str:
    control_dict = case_path / "system" / "controlDict"
    if not control_dict.is_file():
        return "unknown"
    try:
        text = control_dict.read_text()
    except OSError:
        return "unknown"

    header_version = _parse_header_comment_version(text)
    if header_version:
        return header_version

    block_version = _parse_foamfile_block_version(text)
    if block_version:
        return block_version
    return "unknown"


def _parse_header_comment_version(text: str) -> str | None:
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


def _parse_foamfile_block_version(text: str) -> str | None:
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


def _read_optional_entry(file_path: Path, key: str) -> str | None:
    try:
        return read_entry(file_path, key).strip()
    except OpenFOAMError:
        return None


def _boundary_condition_info(file_path: Path, full_key: str) -> list[str]:
    """
    Provide extra info for boundary patches: show type/value when possible.
    """
    parts = full_key.split(".")
    info: list[str] = []
    if "boundaryField" not in parts:
        return info
    idx = parts.index("boundaryField")
    if idx + 1 >= len(parts):
        return info
    patch = parts[idx + 1]
    patch_key = ".".join(parts[: idx + 2])

    bc_type = _read_optional_entry(file_path, f"{patch_key}.type")
    if bc_type:
        info.append(f"BC {patch} type: {bc_type}")
    else:
        info.append(f"BC {patch}: missing required entry 'type'")

    bc_value = _read_optional_entry(file_path, f"{patch_key}.value")
    if bc_value:
        info.append(f"BC {patch} value: {bc_value}")
    else:
        info.append(f"BC {patch}: value entry not found")

    return info


def _guess_validator(key: str) -> Validator:
    """
    Simple heuristic to choose a validator based on key name.
    """
    lower = key.lower()
    if any(tok in lower for tok in ("on", "off", "switch", "enable", "disable")):
        return bool_flag
    if any(tok in lower for tok in ("iter", "step", "n", "count")):
        return as_int
    if any(tok in lower for tok in ("tol", "dt", "time", "coeff", "alpha", "beta")):
        return as_float
    return non_empty


def _choose_validator(key: str, value: str) -> tuple[Validator, str]:
    """
    Choose a validator based on both key name and current value.

    This allows us to handle scalar types and simple vectors.
    """
    # Prefer vector validation when the value looks like a vector.
    # Only treat as vector if it actually parses as a vector; otherwise
    # fall back to scalar / key-based heuristics (e.g. schemes like
    # "div(tauMC) Gauss linear" are not vectors even though they have
    # parentheses in the name).
    if "(" in value and ")" in value:
        vec_error = vector_values(value)
        if vec_error is None:
            return vector_values, "vector"

    # Try to infer scalar type from the value itself: check the last token
    # for a numeric literal before falling back to key-based heuristics.
    tokens = value.replace(";", " ").split()
    if tokens:
        last = tokens[-1]
        try:
            # If this parses as int and looks integer-like, prefer integer.
            int(last)
            if "." not in last and "e" not in last.lower():
                return as_int, "integer"
        except ValueError:
            pass
        try:
            float(last)
        except ValueError:
            pass
        else:
            return as_float, "float"

    validator = _guess_validator(key)
    # Simple label based on which validator was chosen.
    if validator is bool_flag:
        label = "boolean-like"
    elif validator is as_int:
        label = "integer"
    elif validator is as_float:
        label = "float"
    else:
        label = "text"
    return validator, label

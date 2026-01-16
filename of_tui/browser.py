from __future__ import annotations

import curses
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Callable

from .config import get_config, key_in, fzf_enabled
from .editor import Entry, EntryEditor, autoformat_value
from .entry_meta import get_entry_metadata, refresh_entry_cache
from .layout import draw_status_bar, status_message
from .openfoam import OpenFOAMError, list_keywords, read_entry, write_entry
from .validation import Validator


@dataclass(frozen=True)
class BrowserCallbacks:
    show_message: Callable[[Any, str], None]
    view_file: Callable[[Any, Path], None]
    prompt_command: Callable[[Any, Optional[list[str]]], str]
    command_suggestions: Callable[[Path], list[str]]
    handle_command: Callable[[Any, Path, Any, str], Optional[str]]
    mode_status: Callable[[Any], str]


def entry_browser_screen(
    stdscr: Any,
    case_path: Path,
    file_path: Path,
    state: Any,
    callbacks: BrowserCallbacks,
    initial_index: Optional[int] = None,
) -> None:
    """
    Browse entries in a file with a left-hand list and right-hand preview.
    """
    base_entry: Optional[str] = None
    stack: list[tuple[Optional[str], list[str], int]] = []
    cache: dict[str, tuple[str, str, list[str], list[str], list[str]]] = {}
    list_scroll = 0

    try:
        status_message(stdscr, f"Loading entries for {file_path.name}...")
        keywords = list_keywords(file_path)
    except OpenFOAMError as exc:
        callbacks.show_message(
            stdscr, f"Error reading {file_path.relative_to(case_path)}: {exc}"
        )
        return

    if not keywords:
        callbacks.show_message(stdscr, "No entries found in file.")
        return

    index = 0 if initial_index is None else max(0, min(initial_index, len(keywords) - 1))

    while True:
        cfg = get_config()
        key = keywords[index]
        full_key = key if base_entry is None else f"{base_entry}.{key}"

        if full_key not in cache:
            status_message(stdscr, f"Loading {full_key}...")
        value, type_label, subkeys, comments, info_lines, validator = get_entry_metadata(
            cache, file_path, case_path, full_key
        )

        list_scroll = _entry_browser_scroll(index, list_scroll, stdscr, len(keywords))

        _draw_entry_browser(
            stdscr,
            case_path,
            file_path,
            base_entry,
            keywords,
            index,
            list_scroll,
            full_key,
            value,
            type_label,
            subkeys,
            comments,
            info_lines,
            callbacks.mode_status(state),
        )

        key_code = stdscr.getch()

        if key_code in (curses.KEY_UP,) or key_in(key_code, cfg.keys.get("up", [])):
            index = (index - 1) % len(keywords)
        elif key_code in (curses.KEY_DOWN,) or key_in(key_code, cfg.keys.get("down", [])):
            index = (index + 1) % len(keywords)
        elif key_in(key_code, cfg.keys.get("top", [])):
            index = 0
        elif key_in(key_code, cfg.keys.get("bottom", [])):
            index = len(keywords) - 1
        elif key_code in (curses.KEY_LEFT,) or key_in(key_code, cfg.keys.get("back", [])):
            if stack:
                base_entry, keywords, index = stack.pop()
            else:
                return
        elif key_code == ord("o"):
            if _entry_browser_external_edit(
                stdscr, file_path, case_path, cache, full_key, callbacks
            ):
                continue
        elif key_code == ord("v"):
            callbacks.view_file(stdscr, file_path)
        elif key_code in (
            ord("l"),
            ord("e"),
            curses.KEY_RIGHT,
            ord("\n"),
            curses.KEY_ENTER,
        ):
            if subkeys:
                stack.append((base_entry, keywords, index))
                base_entry = full_key
                keywords = subkeys
                index = 0
                continue

            _entry_browser_inline_edit(
                stdscr,
                file_path,
                case_path,
                cache,
                full_key,
                value,
                validator,
                type_label,
                subkeys,
                callbacks,
            )
        elif key_code == curses.KEY_RESIZE:
            continue
        elif key_in(key_code, cfg.keys.get("search", [])):
            new_index = _entry_browser_search(
                stdscr, file_path, case_path, cache, keywords, index, callbacks
            )
            if new_index is not None:
                index = new_index
            continue
        elif key_in(key_code, cfg.keys.get("help", [])):
            _entry_browser_help(stdscr, callbacks)
        elif key_in(key_code, cfg.keys.get("command", [])):
            command = callbacks.prompt_command(stdscr, callbacks.command_suggestions(case_path))
            if not command:
                continue
            if callbacks.handle_command(stdscr, case_path, state, command) == "quit":
                return


def _draw_entry_browser(
    stdscr: Any,
    case_path: Path,
    file_path: Path,
    base_entry: Optional[str],
    keys: list[str],
    current_index: int,
    list_scroll: int,
    full_key: str,
    value: str,
    type_label: str,
    subkeys: list[str],
    comments: list[str],
    info_lines: list[str],
    status_suffix: str,
) -> None:
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    split_col = max(20, width // 2)
    left_width = split_col - 1
    right_width = width - split_col - 1

    try:
        left_win = stdscr.derwin(max(1, height - 1), split_col, 0, 0)
        right_win = stdscr.derwin(max(1, height - 1), max(1, width - split_col), 0, split_col)
    except curses.error:
        left_win = stdscr
        right_win = stdscr

    left_win.erase()
    right_win.erase()

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
    list_rows = max(0, height - 1 - start_row)
    for offset, k in enumerate(keys[list_scroll : list_scroll + list_rows]):
        idx = list_scroll + offset
        if start_row + offset >= height - 1:
            break
        prefix = ">> " if idx == current_index else "   "
        label = (prefix + k)[: max(1, left_width)]
        try:
            left_win.addstr(start_row + offset, 0, label)
        except curses.error:
            break

    try:
        right_win.addstr(0, 0, "Entry preview"[: max(1, right_width)])
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

    base = f"case: {case_path.name} | file: {file_path.relative_to(case_path)} | path: {full_key}"
    status = f"{base} | {status_suffix}" if status_suffix else base
    draw_status_bar(stdscr, status)

    try:
        left_win.noutrefresh()
        right_win.noutrefresh()
        stdscr.noutrefresh()
        curses.doupdate()
    except curses.error:
        stdscr.refresh()


def _entry_browser_scroll(index: int, list_scroll: int, stdscr: Any, total: int) -> int:
    height, _ = stdscr.getmaxyx()
    list_rows = max(0, height - 1 - 4)
    if list_rows > 0:
        if index < list_scroll:
            list_scroll = index
        elif index >= list_scroll + list_rows:
            list_scroll = index - list_rows + 1

        max_scroll = max(0, total - list_rows)
        if list_scroll > max_scroll:
            list_scroll = max_scroll
    else:
        list_scroll = 0
    return list_scroll


def _entry_browser_external_edit(
    stdscr: Any,
    file_path: Path,
    case_path: Path,
    cache: dict[str, tuple[str, str, list[str], list[str], list[str]]],
    full_key: str,
    callbacks: BrowserCallbacks,
) -> bool:
    try:
        original_value = read_entry(file_path, full_key)
    except OpenFOAMError as exc:
        callbacks.show_message(stdscr, f"Failed to read entry for editor: {exc}")
        return False

    edited_value = _open_in_external_editor(stdscr, original_value, callbacks)
    if edited_value is None or edited_value == original_value:
        return False

    formatted = autoformat_value(edited_value)
    if not write_entry(file_path, full_key, formatted):
        callbacks.show_message(stdscr, "Failed to save value from editor.")
        return False

    refresh_entry_cache(cache, file_path, case_path, full_key)
    return True


def _entry_browser_inline_edit(
    stdscr: Any,
    file_path: Path,
    case_path: Path,
    cache: dict[str, tuple[str, str, list[str], list[str], list[str]]],
    full_key: str,
    value: str,
    validator: Validator,
    type_label: str,
    subkeys: list[str],
    callbacks: BrowserCallbacks,
) -> None:
    entry = Entry(key=full_key, value=value)

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
    refresh_entry_cache(cache, file_path, case_path, full_key)


def _entry_browser_search(
    stdscr: Any,
    file_path: Path,
    case_path: Path,
    cache: dict[str, tuple[str, str, list[str], list[str], list[str]]],
    keywords: list[str],
    index: int,
    callbacks: BrowserCallbacks,
) -> Optional[int]:
    if fzf_enabled():
        return _fzf_pick_entry_in_file(stdscr, keywords)

    curses.echo()
    stdscr.clear()
    stdscr.addstr("Search (keys/values/comments): ")
    stdscr.refresh()
    query = stdscr.getstr().decode()
    curses.noecho()
    if not query:
        return None

    new_index = _search_entries(
        file_path, case_path, cache, keywords, index, query, direction=1
    )
    if new_index is None:
        callbacks.show_message(stdscr, f"No matches for '{query}'.")
    return new_index


def _entry_browser_help(stdscr: Any, callbacks: BrowserCallbacks) -> None:
    callbacks.show_message(
        stdscr,
        "Keys: j/k or arrows move, g/G top/bottom, l/e/Right/Enter edit, h/Left/q back, v view file, / search, : command line, ? help\n\nCommands:\n  :check  :tools  :diag  :run  :nofoam  :tool <name>  :quit",
    )


def _search_entries(
    file_path: Path,
    case_path: Path,
    cache: dict[str, tuple[str, str, list[str], list[str], list[str]]],
    keywords: list[str],
    current_index: int,
    query: str,
    direction: int = 1,
) -> Optional[int]:
    if not keywords:
        return None

    q = query.lower()

    n = len(keywords)
    for step in range(1, n + 1):
        idx = (current_index + direction * step) % n
        key = keywords[idx]
        full_key = key
        value, _type_label, _subkeys, comments, _info_lines, _validator = get_entry_metadata(
            cache, file_path, case_path, full_key
        )
        haystack = " ".join([key, value] + comments).lower()
        if q in haystack:
            return idx

    return None


def _fzf_pick_entry_in_file(stdscr: Any, keywords: list[str]) -> Optional[int]:
    if not keywords:
        return None

    fzf_input = "\n".join(keywords)

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


def _open_in_external_editor(
    stdscr: Any, initial_text: str, callbacks: BrowserCallbacks
) -> Optional[str]:
    editor = os.environ.get("EDITOR") or "vi"

    try:
        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(initial_text)
    except OSError as exc:
        callbacks.show_message(stdscr, f"Failed to create temp file for editor: {exc}")
        return None

    curses.endwin()
    try:
        subprocess.run([editor, str(tmp_path)], check=False)
    finally:
        stdscr.clear()
        stdscr.refresh()

    try:
        edited = tmp_path.read_text()
    except OSError as exc:
        callbacks.show_message(stdscr, f"Failed to read edited value: {exc}")
        return None
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    return edited

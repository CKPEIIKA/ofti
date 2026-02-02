from __future__ import annotations

import curses
import os
import tempfile
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ofti.core.entries import Entry, autoformat_value
from ofti.core.entry_io import list_keywords, read_entry
from ofti.core.entry_meta import get_entry_metadata, refresh_entry_cache
from ofti.core.tool_dicts_service import apply_assignment_or_write
from ofti.core.validation import Validator
from ofti.foam.config import fzf_enabled, get_config, key_hint, key_in
from ofti.foam.exceptions import QuitAppError
from ofti.foam.openfoam import OpenFOAMError
from ofti.foam.subprocess_utils import resolve_executable, run_trusted
from ofti.ui_curses.entry_editor import EntryEditor
from ofti.ui_curses.inputs import prompt_input
from ofti.ui_curses.layout import draw_status_bar, status_message
from ofti.ui_curses.viewer import Viewer


@dataclass(frozen=True)
class BrowserCallbacks:
    show_message: Callable[[Any, str], None]
    view_file: Callable[[Any, Path], None]
    prompt_command: Callable[[Any, list[str] | None], str]
    command_suggestions: Callable[[Path], list[str]]
    handle_command: Callable[[Any, Path, Any, str], str | None]
    mode_status: Callable[[Any], str]


def entry_browser_screen(
    stdscr: Any,
    case_path: Path,
    file_path: Path,
    state: Any,
    callbacks: BrowserCallbacks,
    initial_index: int | None = None,
) -> None:
    """
    Browse entries in a file with a left-hand list and right-hand preview.
    """
    base_entry: str | None = None
    stack: list[tuple[str | None, list[str], int]] = []
    cfg = get_config()
    use_cache = cfg.enable_entry_cache
    crawl_enabled = cfg.enable_background_entry_crawl and use_cache
    cache: dict[str, tuple[str, str, list[str], list[str], list[str]]] = {}
    list_scroll = 0
    last_key: str | None = None
    last_meta: tuple[str, str, list[str], list[str], list[str], Validator] | None = None
    crawl_stop = threading.Event()

    try:
        status_message(stdscr, f"Loading entries for {file_path.name}...")
        keywords = list_keywords(file_path)
    except OpenFOAMError as exc:
        callbacks.show_message(
            stdscr, f"Error reading {file_path.relative_to(case_path)}: {exc}",
        )
        return

    if not keywords:
        callbacks.show_message(stdscr, "No entries found in file.")
        return

    index = 0 if initial_index is None else max(0, min(initial_index, len(keywords) - 1))
    if crawl_enabled:
        _start_entry_crawl(file_path, keywords, cache, crawl_stop)

    while True:
        cfg = get_config()
        key = keywords[index]
        full_key = key if base_entry is None else f"{base_entry}.{key}"

        if full_key != last_key or last_meta is None:
            status_message(stdscr, f"Loading {full_key}...")
            value, type_label, subkeys, comments, info_lines, validator = get_entry_metadata(
                cache if use_cache else {}, file_path, full_key,
            )
            last_key = full_key
            last_meta = (value, type_label, subkeys, comments, info_lines, validator)
        else:
            value, type_label, subkeys, comments, info_lines, validator = last_meta

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

        if key_in(key_code, cfg.keys.get("quit", [])):
            raise QuitAppError()
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
                crawl_stop.set()
                return
        elif key_code == ord("o"):
            if _entry_browser_external_edit(
                stdscr, file_path, cache, full_key, callbacks, use_cache,
            ):
                last_key = None
                last_meta = None
                continue
        elif key_in(key_code, cfg.keys.get("view", [])):
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
                crawl_stop.set()
                if crawl_enabled:
                    crawl_stop = threading.Event()
                    cache.clear()
                _start_entry_crawl(file_path, keywords, cache, crawl_stop)
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
                use_cache,
            )
            last_key = None
            last_meta = None
        elif key_code == curses.KEY_RESIZE:
            continue
        elif key_code == ord("c"):
            if validator is None:
                callbacks.show_message(stdscr, "No validator available for this entry.")
            else:
                error = validator(value)
                if error:
                    callbacks.show_message(stdscr, f"Check failed: {error}")
                else:
                    callbacks.show_message(stdscr, "Check OK.")
        elif key_in(key_code, cfg.keys.get("search", [])):
            new_index = _entry_browser_search(
                stdscr, keywords, index, callbacks,
            )
            if new_index is not None:
                index = new_index
            continue
        elif key_in(key_code, cfg.keys.get("help", [])):
            _entry_browser_help(stdscr, callbacks)
        elif key_code == ord("K"):
            _entry_browser_context_help(
                stdscr,
                full_key,
                type_label,
                value,
                comments,
                info_lines,
                subkeys,
            )
        elif key_in(key_code, cfg.keys.get("command", [])):
            command = callbacks.prompt_command(stdscr, callbacks.command_suggestions(case_path))
            if not command:
                continue
            if callbacks.handle_command(stdscr, case_path, state, command) == "quit":
                crawl_stop.set()
                return


def _draw_entry_browser(
    stdscr: Any,
    case_path: Path,
    file_path: Path,
    base_entry: str | None,
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
        view_hint = key_hint("view", "v")
        back_hint = key_hint("back", "h")
        left_win.addstr(
            2,
            0,
            (
                f"j/k: move  l: edit  o: edit section  c: check  K: help  "
                f"{view_hint}: view  {back_hint}: back"
            )[: max(1, left_width)],
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
    with suppress(curses.error):
        right_win.addstr(row, 0, "Current value:"[: max(1, right_width)])
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
        with suppress(curses.error):
            right_win.addstr(row, 0, "Comments:"[: max(1, right_width)])
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
        with suppress(curses.error):
            right_win.addstr(row, 0, "Info:"[: max(1, right_width)])
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
        with suppress(curses.error):
            right_win.addstr(row, 0, "Sub-keys:"[: max(1, right_width)])
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
        list_scroll = min(list_scroll, max_scroll)
    else:
        list_scroll = 0
    return list_scroll


def _entry_browser_external_edit(
    stdscr: Any,
    file_path: Path,
    cache: dict[str, tuple[str, str, list[str], list[str], list[str]]],
    full_key: str,
    callbacks: BrowserCallbacks,
    use_cache: bool,
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
    if not apply_assignment_or_write(case_path, file_path, full_key.split("."), formatted):
        callbacks.show_message(stdscr, "Failed to save value from editor.")
        return False

    if use_cache:
        refresh_entry_cache(cache, file_path, full_key)
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
    use_cache: bool,
) -> None:
    _ = callbacks
    entry = Entry(key=full_key, value=value)

    def on_save(new_value: str) -> bool:
        formatted = autoformat_value(new_value)
        return apply_assignment_or_write(case_path, file_path, full_key.split("."), formatted)

    editor = EntryEditor(
        stdscr,
        entry,
        on_save,
        validator=validator,
        type_label=type_label,
        subkeys=subkeys,
        case_label=case_path.name,
    )
    editor.edit()
    if use_cache:
        refresh_entry_cache(cache, file_path, full_key)


def _entry_browser_search(
    stdscr: Any,
    keywords: list[str],
    index: int,
    callbacks: BrowserCallbacks,
) -> int | None:
    if fzf_enabled():
        return _fzf_pick_entry_in_file(stdscr, keywords)

    stdscr.clear()
    query = prompt_input(stdscr, "Search (keys/values/comments): ")
    if query is None:
        return None
    query = query.strip()
    if not query:
        return None

    new_index = _search_entries(keywords, index, query, direction=1)
    if new_index is None:
        callbacks.show_message(stdscr, f"No matches for '{query}'.")
    return new_index


def _entry_browser_help(stdscr: Any, callbacks: BrowserCallbacks) -> None:
    view_hint = key_hint("view", "v")
    back_hint = key_hint("back", "h")
    callbacks.show_message(
        stdscr,
        "Keys: j/k or arrows move, g/G top/bottom, l/e/Right/Enter edit, "
        f"{back_hint}/Left back, {view_hint} view file, c check, / search, : command line, "
        "K entry help, ? help\n\n"
        "Commands:\n  :check  :tools  :diag  :run  :tool <name>  :quit",
    )


def _entry_browser_context_help(
    stdscr: Any,
    full_key: str,
    type_label: str,
    value: str,
    comments: list[str],
    info_lines: list[str],
    subkeys: list[str],
) -> None:
    lines = [f"Entry help: {full_key}", "", f"Type: {type_label}"]
    if value:
        lines += ["", "Current value:", value]
    if comments:
        lines += ["", "Comments:", *comments]
    if info_lines:
        lines += ["", "Info:", *info_lines]
    if subkeys:
        lines += ["", "Sub-keys:", *[f"- {sk}" for sk in subkeys]]
    Viewer(stdscr, "\n".join(lines)).display()


def _search_entries(
    keywords: list[str],
    current_index: int,
    query: str,
    direction: int = 1,
) -> int | None:
    if not keywords:
        return None

    q = query.lower()

    n = len(keywords)
    for step in range(1, n + 1):
        idx = (current_index + direction * step) % n
        key = keywords[idx]
        if q in key.lower():
            return idx

    return None


def _fzf_pick_entry_in_file(stdscr: Any, keywords: list[str]) -> int | None:
    if not keywords:
        return None

    fzf_input = "\n".join(keywords)

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
            return None
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
    stdscr: Any, initial_text: str, callbacks: BrowserCallbacks,
) -> str | None:
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
        resolved = resolve_executable(editor)
        run_trusted([resolved, str(tmp_path)], capture_output=False, check=False)
    finally:
        stdscr.clear()
        stdscr.refresh()

    try:
        edited = tmp_path.read_text()
    except OSError as exc:
        callbacks.show_message(stdscr, f"Failed to read edited value: {exc}")
        return None
    finally:
        with suppress(OSError):
            tmp_path.unlink()

    return edited


def _start_entry_crawl(
    file_path: Path,
    keywords: list[str],
    cache: dict[str, tuple[str, str, list[str], list[str], list[str]]],
    stop_event: threading.Event,
) -> threading.Thread:
    def worker() -> None:
        for key in keywords:
            if stop_event.is_set():
                return
            _ = get_entry_metadata(cache, file_path, key)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread

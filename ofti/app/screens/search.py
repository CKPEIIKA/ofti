from __future__ import annotations

import contextlib
import curses
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from ofti.app.helpers import show_message
from ofti.app.state import AppState
from ofti.core.domain import Case, DictionaryFile, EntryRef
from ofti.core.entry_io import list_keywords
from ofti.foam.config import fzf_enabled
from ofti.foam.openfoam import OpenFOAMError, discover_case_files
from ofti.foam.subprocess_utils import resolve_executable
from ofti.ui.status import status_message
from ofti.ui_curses.entry_browser import BrowserCallbacks, entry_browser_screen


def global_search_screen(
    stdscr: Any,
    case_path: Path,
    state: AppState,
    *,
    browser_callbacks: BrowserCallbacks,
) -> None:
    """Global search wrapper around `fzf`."""
    try:
        _run_global_search(stdscr, case_path, state, browser_callbacks)
    except _GlobalSearchAbortError as exc:
        if exc.message:
            show_message(stdscr, exc.message)
    except Exception as exc:
        show_message(stdscr, f"Global search failed: {exc}")


class _GlobalSearchAbortError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _run_global_search(
    stdscr: Any,
    case_path: Path,
    state: AppState,
    browser_callbacks: BrowserCallbacks,
) -> None:
    if not fzf_enabled():
        raise _GlobalSearchAbortError("fzf not available (disabled or missing).")

    _ensure_search_index_case(state, case_path)
    entries, skipped_files = _build_top_level_index(stdscr, case_path, state)
    _start_full_index_build(case_path, state)

    if not entries:
        if skipped_files:
            raise _GlobalSearchAbortError(
                "No entries found for global search. "
                f"{skipped_files} file(s) could not be parsed; run Check syntax for details.",
            )
        raise _GlobalSearchAbortError("No entries found for global search.")

    curses.def_prog_mode()
    curses.endwin()
    try:
        try:
            result = _run_fzf_live(case_path, state, entries)
        except FileNotFoundError as exc:
            raise _GlobalSearchAbortError("fzf not found.") from exc
    finally:
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
        raise _GlobalSearchAbortError(f"Failed to load keys for {rel_str}: {exc}") from exc
    except Exception as exc:
        raise _GlobalSearchAbortError(
            f"Failed to load keys for {rel_str}: unexpected parser error ({exc}).",
        ) from exc

    base_key = full_key.split(".", 1)[0]
    try:
        initial_index = keys.index(base_key)
    except ValueError:
        initial_index = 0

    entry_browser_screen(
        stdscr,
        case_path,
        file_path,
        state,
        browser_callbacks,
        initial_index=initial_index,
    )


def _run_fzf_live(
    case_path: Path,
    state: AppState,
    entries: list[EntryRef],
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.Popen(  # noqa: S603
        [resolve_executable("fzf")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    sent: set[tuple[str, str]] = set()
    stdin_pipe = proc.stdin

    def send_new(rows: list[tuple[str, str]]) -> bool:
        nonlocal stdin_pipe
        if stdin_pipe is None or stdin_pipe.closed:
            return False
        added = False
        for row in rows:
            if row in sent:
                continue
            stdin_pipe.write(f"{row[0]}\t{row[1]}\n")
            sent.add(row)
            added = True
        if added:
            stdin_pipe.flush()
        return added

    send_new([(ref.file.rel, ref.key) for ref in entries])

    close_sent = False
    while proc.poll() is None:
        with state.search_index_lock:
            if state.search_index_case != case_path.resolve():
                break
            snapshot = list(state.search_index_entries)
            full_done = state.search_index_full
        try:
            send_new(snapshot)
        except (BrokenPipeError, OSError, ValueError):
            break
        if full_done and not close_sent and stdin_pipe is not None and not stdin_pipe.closed:
            with contextlib.suppress(OSError):
                stdin_pipe.close()
            close_sent = True
        time.sleep(0.1)

    if proc.poll() is None:
        with contextlib.suppress(OSError):
            proc.terminate()
    # `communicate()` can flush stdin; force-disable it after any manual close.
    with contextlib.suppress(OSError):
        if proc.stdin is not None and not proc.stdin.closed:
            proc.stdin.close()
    proc.stdin = None
    try:
        stdout, stderr = proc.communicate()
    except ValueError:
        stdout, stderr = "", ""
    return subprocess.CompletedProcess(
        args=["fzf"],
        returncode=proc.returncode if proc.returncode is not None else 1,
        stdout=stdout,
        stderr=stderr,
    )


def _collect_search_keys(file_path: Path, *, max_depth: int = 6) -> list[str]:
    del max_depth
    top_keys = list_keywords(file_path)
    collected: list[str] = []
    seen: set[str] = set()

    def add(key: str) -> None:
        if key and key not in seen:
            seen.add(key)
            collected.append(key)

    for key in top_keys:
        add(key)
    for key in _collect_search_keys_text(file_path):
        add(key)
    return collected


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_+.-]*$")


def _collect_search_keys_text(file_path: Path) -> list[str]:
    try:
        text = file_path.read_text(errors="ignore")
    except OSError:
        return []

    keys: list[str] = []
    seen: set[str] = set()
    stack: list[str] = []
    in_block_comment = False
    pending_block: str | None = None

    def add_key(name: str) -> None:
        if not _IDENT.match(name):
            return
        dotted = ".".join([*stack, name]) if stack else name
        if dotted not in seen:
            seen.add(dotted)
            keys.append(dotted)

    for raw in text.splitlines():
        line = raw
        while True:
            if in_block_comment:
                end = line.find("*/")
                if end == -1:
                    line = ""
                    break
                line = line[end + 2 :]
                in_block_comment = False
                continue
            start = line.find("/*")
            if start == -1:
                break
            end = line.find("*/", start + 2)
            if end == -1:
                line = line[:start]
                in_block_comment = True
                break
            line = line[:start] + line[end + 2 :]
        line = line.split("//", 1)[0].strip()
        if not line:
            continue

        if line == "{":
            if pending_block:
                add_key(pending_block)
                stack.append(pending_block)
                pending_block = None
            continue
        if line.startswith("}"):
            pending_block = None
            closes = line.count("}")
            for _ in range(closes):
                if stack:
                    stack.pop()
            continue

        if "{" in line:
            left = line.split("{", 1)[0].strip()
            candidate = left.split()[0] if left else ""
            if _IDENT.match(candidate):
                add_key(candidate)
                stack.append(candidate)
            pending_block = None
            continue

        if line.endswith(";"):
            token = line[:-1].strip().split()[0]
            if _IDENT.match(token):
                add_key(token)
            pending_block = None
            continue

        token = line.split()[0]
        if _IDENT.match(token):
            pending_block = token
            continue
        pending_block = None

    return keys


def _ensure_search_index_case(state: AppState, case_path: Path) -> None:
    case_root = case_path.resolve()
    with state.search_index_lock:
        if state.search_index_case == case_root:
            return
        state.search_index_case = case_root
        state.search_index_files = []
        state.search_index_entries = []
        state.search_index_full = False
        state.search_index_building = False


def _build_top_level_index(
    stdscr: Any,
    case_path: Path,
    state: AppState,
) -> tuple[list[EntryRef], int]:
    with state.search_index_lock:
        cached_files = list(state.search_index_files)
        cached_entries = list(state.search_index_entries)
        full_ready = state.search_index_full
    if cached_entries and full_ready:
        return _refs_from_cached(case_path, cached_entries), 0
    if cached_entries and cached_files:
        return _refs_from_cached(case_path, cached_entries), 0

    foam_case = Case(root=case_path)
    sections = discover_case_files(foam_case.root)
    skipped_files = 0
    entries: list[tuple[str, str]] = []
    files: list[str] = []

    for group in sections.values():
        for file_path in group:
            rel = file_path.relative_to(case_path).as_posix()
            files.append(rel)
            status_message(stdscr, f"Indexing {rel}...")
            try:
                keys = list_keywords(file_path)
            except OpenFOAMError:
                skipped_files += 1
                continue
            except Exception:
                skipped_files += 1
                continue
            for key in keys:
                entries.append((rel, key))

    entries = _dedupe_entries(entries)
    with state.search_index_lock:
        state.search_index_files = files
        state.search_index_entries = entries
        state.search_index_full = False
    return _refs_from_cached(case_path, entries), skipped_files


def _start_full_index_build(case_path: Path, state: AppState) -> None:
    with state.search_index_lock:
        if state.search_index_full or state.search_index_building:
            return
        files = list(state.search_index_files)
        state.search_index_building = True
        case_root = state.search_index_case

    def worker() -> None:
        try:
            entries: list[tuple[str, str]] = []
            for rel in files:
                file_path = case_path / rel
                try:
                    keys = _collect_search_keys(file_path)
                except Exception:
                    continue
                for key in keys:
                    entries.append((rel, key))
            entries = _dedupe_entries(entries)
            with state.search_index_lock:
                if state.search_index_case != case_root:
                    return
                state.search_index_entries = entries
                state.search_index_full = True
        finally:
            with state.search_index_lock:
                if state.search_index_case == case_root:
                    state.search_index_building = False

    threading.Thread(target=worker, daemon=True).start()


def _refs_from_cached(case_path: Path, entries: list[tuple[str, str]]) -> list[EntryRef]:
    foam_case = Case(root=case_path)
    refs: list[EntryRef] = []
    for rel, key in entries:
        dict_file = DictionaryFile(foam_case.root, case_path / rel)
        refs.append(EntryRef(dict_file, key))
    return refs


def _dedupe_entries(entries: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[tuple[str, str]] = []
    for item in entries:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped

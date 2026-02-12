from __future__ import annotations

import curses
from pathlib import Path
from typing import Any

from ofti.app.helpers import show_message
from ofti.app.state import AppState
from ofti.core.domain import Case, DictionaryFile, EntryRef
from ofti.core.entry_io import list_keywords
from ofti.foam.config import fzf_enabled
from ofti.foam.openfoam import OpenFOAMError, discover_case_files
from ofti.foam.subprocess_utils import run_trusted
from ofti.foamlib import adapter as foamlib_integration
from ofti.ui_curses.entry_browser import BrowserCallbacks, entry_browser_screen
from ofti.ui.status import status_message


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

    foam_case = Case(root=case_path)
    sections = discover_case_files(foam_case.root)
    entries: list[EntryRef] = []

    for files in sections.values():
        for file_path in files:
            status_message(stdscr, f"Indexing {file_path.relative_to(case_path)}...")
            dict_file = DictionaryFile(foam_case.root, file_path)
            try:
                if foamlib_integration.is_foam_file(file_path):
                    keys = foamlib_integration.list_keywords(file_path)
                else:
                    keys = list_keywords(file_path)
            except OpenFOAMError as exc:
                if state.no_foam:
                    raise _GlobalSearchAbortError(
                        "Global search failed: "
                        f"{exc} (OpenFOAM env not available)",
                    ) from exc
                continue
            entries.extend(EntryRef(dict_file, key) for key in keys)

    if not entries:
        raise _GlobalSearchAbortError("No entries found for global search.")

    fzf_input = "\n".join(f"{ref.file.rel}\t{ref.key}" for ref in entries)

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

    base_key = full_key.split(".")[-1]
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

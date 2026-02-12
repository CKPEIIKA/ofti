from __future__ import annotations

import curses
from contextlib import suppress
from pathlib import Path
from typing import Any

from ofti.core.checkmesh import extract_last_courant
from ofti.foam.config import get_config, key_hint, key_in
from ofti.tools.logs_analysis import log_analysis_screen
from ofti.tools.logs_select import _select_log_file
from ofti.tools.menu_helpers import build_menu
from ofti.tools.runner import _show_message
from ofti.ui_curses.viewer import Viewer


def logs_screen(stdscr: Any, case_path: Path) -> None:
    """Logs menu: view, tail, and analysis in one place."""
    while True:
        labels = [
            "View log file",
            "Tail log (live)",
            "[a] Log analysis summary",
            "Back",
        ]
        menu = build_menu(
            stdscr,
            "View logs",
            labels,
            menu_key="menu:view_logs",
            item_hint="Choose how to inspect logs.",
        )
        choice = menu.navigate()
        if choice in (-1, len(labels) - 1):
            return
        if choice == 1:
            log_tail_screen(stdscr, case_path)
            continue
        if choice == 2:
            log_analysis_screen(stdscr, case_path)
            continue

        path = _select_log_file(case_path, stdscr, title="Select log file to view")
        if path is None:
            continue
        try:
            text = path.read_text()
        except OSError as exc:
            _show_message(stdscr, f"Failed to read {path.name}: {exc}")
            continue

        viewer = Viewer(stdscr, text)
        viewer.display()


def log_tail_screen(stdscr: Any, case_path: Path) -> None:  # noqa: C901, PLR0912
    log_files = sorted(case_path.glob("log.*"))
    if not log_files:
        _show_message(stdscr, "No log.* files found in case directory.")
        return

    labels = [p.name for p in log_files]
    menu = build_menu(
        stdscr,
        "Select log to tail",
        [*labels, "Back"],
        menu_key="menu:log_tail_select",
        item_hint="Select log to tail.",
    )
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return

    path = log_files[choice]
    cfg = get_config()
    patterns = ["FATAL", "bounding", "Courant", "nan", "SIGFPE", "floating point exception"]
    stdscr.timeout(500)
    try:
        while True:
            try:
                text = path.read_text(errors="ignore")
            except OSError as exc:
                _show_message(stdscr, f"Failed to read {path.name}: {exc}")
                return

            lines = text.splitlines()[-50:]
            last_courant = extract_last_courant(lines)
            has_fpe = any("floating point exception" in line.lower() for line in lines)
            has_nan = any("nan" in line.lower() for line in lines)
            alerts = []
            if last_courant is not None and last_courant > cfg.courant_limit:
                alerts.append(f"Courant>{cfg.courant_limit:g}")
            if has_fpe:
                alerts.append("FPE")
            if has_nan:
                alerts.append("NaN")
            stdscr.clear()
            height, width = stdscr.getmaxyx()
            back_hint = key_hint("back", "h")
            header = f"Tailing {path.name} ({back_hint} to exit)"
            with suppress(curses.error):
                stdscr.addstr(header[: max(1, width - 1)] + "\n")
            with suppress(curses.error):
                highlight = "Highlight: " + ", ".join(patterns)
                if last_courant is not None:
                    highlight += f" | Courant max: {last_courant:g}"
                if alerts:
                    highlight += " | ALERT: " + ", ".join(alerts)
                stdscr.addstr(highlight[: max(1, width - 1)] + "\n\n")
            for line in lines:
                if stdscr.getyx()[0] >= height - 1:
                    break
                mark = ""
                if any(pat.lower() in line.lower() for pat in patterns):
                    mark = "!! "
                    with suppress(curses.error):
                        stdscr.attron(curses.A_BOLD)
                try:
                    stdscr.addstr((mark + line)[: max(1, width - 1)] + "\n")
                except curses.error:
                    break
                if mark:
                    with suppress(curses.error):
                        stdscr.attroff(curses.A_BOLD)
            stdscr.refresh()
            key = stdscr.getch()
            if key_in(key, get_config().keys.get("back", [])):
                return
    finally:
        stdscr.timeout(-1)

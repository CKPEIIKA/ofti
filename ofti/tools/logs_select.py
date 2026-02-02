from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.core.case import detect_solver
from ofti.tools.menu_helpers import build_menu
from ofti.tools.runner import _show_message


def _tail_text(text: str, max_lines: int = 20) -> str:
    lines = text.strip().splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines) if lines else "(empty)"
    tail = "\n".join(lines[-max_lines:])
    return f"... ({len(lines) - max_lines} lines omitted)\n{tail}"


def _preferred_log_file(case_path: Path) -> Path | None:
    solver = detect_solver(case_path)
    if solver and solver != "unknown":
        candidate = case_path / f"log.{solver}"
        if candidate.is_file():
            return candidate
    logs = sorted(case_path.glob("log.*"), key=lambda p: p.stat().st_mtime)
    if logs:
        return logs[-1]
    return None


def _select_log_file(
    case_path: Path,
    stdscr: Any,
    *,
    title: str = "Select log file",
) -> Path | None:
    log_files = sorted(case_path.glob("log.*"))
    if not log_files:
        _show_message(stdscr, "No log.* files found in case directory.")
        return None
    labels = [p.name for p in log_files]
    menu = build_menu(
        stdscr,
        title,
        [*labels, "Back"],
        menu_key="menu:logs_select",
        item_hint="Select log file.",
    )
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return None
    return log_files[choice]


def _select_solver_log_file(
    case_path: Path,
    stdscr: Any,
    *,
    title: str,
) -> Path | None:
    solver = detect_solver(case_path)
    if not solver or solver == "unknown":
        _show_message(stdscr, "Solver not detected; cannot pick solver logs.")
        return None
    log_files = sorted(case_path.glob(f"log.{solver}*"))
    if not log_files:
        _show_message(stdscr, f"No log.{solver}* files found in case directory.")
        return None
    labels = [p.name for p in log_files]
    menu = build_menu(
        stdscr,
        title,
        [*labels, "Back"],
        menu_key="menu:logs_select_solver",
        item_hint="Select solver log.",
    )
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return None
    return log_files[choice]

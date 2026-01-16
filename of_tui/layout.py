from __future__ import annotations

import curses
import itertools
from typing import Any


_SPINNER = itertools.cycle("|/-\\")


def next_spinner() -> str:
    return next(_SPINNER)


def draw_status_bar(stdscr: Any, text: str) -> None:
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


def status_message(stdscr: Any, message: str) -> None:
    try:
        height, width = stdscr.getmaxyx()
        spinner = next_spinner()
        stdscr.attron(curses.A_REVERSE)
        stdscr.addstr(
            height - 1,
            0,
            f"{spinner} {message}"[: max(1, width - 1)].ljust(max(1, width - 1)),
        )
        stdscr.attroff(curses.A_REVERSE)
        stdscr.refresh()
    except curses.error:
        pass


def case_overview_lines(_meta: dict[str, str]) -> list[str]:
    # No separate dashboard block; header banner carries the summary.
    return []


def case_banner_lines(meta: dict[str, str]) -> list[str]:
    rows = [
        (f"Case: {meta['case_name']}", f"Solver: {meta['solver']}"),
        (f"Status: {meta['status']}", f"Latest time: {meta['latest_time']}"),
        (f"Mesh: {meta['mesh']}", f"Parallel: {meta['parallel']}"),
        (f"Env: {meta['foam_version']}", f"Case header version: {meta['case_header_version']}"),
        (f"Path: {meta['case_path']}", ""),
    ]
    return foam_style_banner("of_tui", rows)


def foam_style_banner(label: str, rows: list[tuple[str, str]]) -> list[str]:
    top = f"/*--------------------------------*- {label} -*----------------------------------*\\"
    bottom = "\\*---------------------------------------------------------------------------*/"
    lines = [top]
    for left, right in rows:
        lines.append(format_banner_row(left, right))
    lines.append(bottom)
    return lines


def format_banner_row(left: str, right: str, column_width: int = 36) -> str:
    def clip(text: str) -> str:
        return text[:column_width]

    return f"| {clip(left).ljust(column_width)} | {clip(right).ljust(column_width)} |"

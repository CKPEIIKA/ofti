from __future__ import annotations

import curses
from typing import Any

from ofti.core.spinner import next_spinner


def draw_status_bar(stdscr: Any, text: str) -> None:
    """Draw a simple status bar on the last line of the screen.
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


def case_overview_lines(meta: dict[str, str], *, compact: bool = False) -> list[str]:
    if compact:
        return []
    return [
        (
            "Captains Deck opens the read-only control deck: live cases, alerts, lint, "
            "mesh/resource watch, scopes, and log radar."
        ),
        (
            f"Current: {meta.get('status', 'unknown')} | "
            f"latest={meta.get('latest_time', 'n/a')} | "
            f"log={meta.get('log', 'none')}"
        ),
    ]


def case_banner_lines(meta: dict[str, str]) -> list[str]:
    env_label = f"Env: {meta['foam_version']}"
    header_version = meta.get("case_header_version", "unknown")
    if (
        header_version
        and header_version != "unknown"
        and header_version != meta.get("foam_version")
    ):
        env_label = f"{env_label} (header v {header_version})"
    status_text = f"Status: {meta['status']}"
    latest_text = f"Latest time: {meta['latest_time']}"
    if meta.get("running") == "yes":
        status_text = (
            f"Running: jobs={meta.get('jobs_running', '0')} "
            f"pids={meta.get('live_processes', '0')}"
        )
        latest_text = (
            f"Latest: {meta['latest_time']} "
            f"iter={meta.get('latest_iteration', 'n/a')}"
        )

    rows = [
        (f"Case: {meta['case_name']}", f"Solver: {meta['solver']}"),
        (status_text, latest_text),
        (
            f"Mesh: {meta['mesh']} Cells: {meta.get('cells', 'n/a')}",
            f"Parallel: {meta['parallel']}",
        ),
        (f"Faces: {meta.get('faces', 'n/a')} Points: {meta.get('points', 'n/a')}",
         f"Disk: {meta.get('disk', 'n/a')}"),
        (env_label, "Keys: ? help / search : cmd"),
        (f"Path: {meta['case_path']}", f"Log: {meta.get('log', 'none')}"),
    ]
    if meta.get("running") == "yes":
        rows.insert(
            4,
            (
                (
                    f"dt={meta.get('latest_delta_t', 'n/a')} "
                    f"sec/iter={meta.get('sec_per_iter', 'n/a')}"
                ),
                f"ETA end={meta.get('eta_end', 'n/a')} criteria={meta.get('eta_criteria', 'n/a')}",
            ),
        )
        rows[-1] = (
            f"Path: {meta['case_path']}",
            f"Log: {meta.get('log', 'none')} {meta.get('log_fresh', '')}".rstrip(),
        )
    return foam_style_banner("ofti", rows)


def compact_case_banner_lines(meta: dict[str, str], width: int = 80) -> list[str]:
    width = max(20, width)
    pieces = [
        "OFTI",
        f"case={meta.get('case_name', 'unknown')}",
        f"solver={meta.get('solver', 'unknown')}",
        f"status={meta.get('status', 'unknown')}",
        f"t={meta.get('latest_time', 'n/a')}",
    ]
    path = str(meta.get("case_path", ""))
    return [
        _clip_join(pieces, width),
        _clip_join([f"mesh={meta.get('mesh', 'unknown')}", f"path={path}"], width),
    ]


def status_chip(value: object) -> str:
    text = str(value or "unknown").lower()
    if text in {"ok", "clean", "ready", "ran", "done", "pass", "passed"}:
        return "[OK]"
    if text in {"running", "run"}:
        return "[RUN]"
    if text in {"warn", "warning", "caution"}:
        return "[WARN]"
    if text in {"error", "fail", "failed", "crit", "critical"}:
        return "[CRIT]"
    return "[--]"


def ascii_meter(value: float | int | None, *, width: int = 12) -> str:
    width = max(1, width)
    if value is None:
        return "[" + "." * width + "]"
    bounded = min(1.0, max(0.0, float(value)))
    filled = round(bounded * width)
    return "[" + "#" * filled + "." * (width - filled) + "]"


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


def _clip_join(parts: list[str], width: int) -> str:
    return " | ".join(parts)[: max(1, width - 1)]

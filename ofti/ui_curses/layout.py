from __future__ import annotations

import curses
from typing import Any

from ofti.core.spinner import next_spinner


def draw_status_bar(stdscr: Any, text: str) -> None:
    """Draw a simple status bar on the last line of the screen."""
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


_BANNER_COLUMN_WIDTH = 36
# FoamFile `version 2.0;` is the dictionary file-format version, not an
# OpenFOAM release, so it is never shown as a case version.
_FOAMFILE_FORMAT_VERSION = "2.0"
_QUALITY_PREFIXES = ("skew=", "nonOrth=")
_COUNT_UNITS = ((1_000_000_000, "G"), (1_000_000, "M"), (100_000, "k"))
_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600


def case_banner_lines(meta: dict[str, str]) -> list[str]:
    running = meta.get("running") == "yes"
    rows = [
        (f"Case: {meta.get('case_name', '?')}", f"Solver: {meta.get('solver', 'unknown')}"),
        _status_row(meta, running=running),
        (_mesh_label(meta), f"Parallel: {meta.get('parallel', 'n/a')}"),
        (_quality_label(meta), f"Disk: {meta.get('disk', 'n/a')}"),
    ]
    if running:
        rows.append(
            (
                f"dt={_number(meta.get('latest_delta_t'))} s/iter={_number(meta.get('sec_per_iter'))}",
                f"ETA end={_duration(meta.get('eta_end'))} criteria={_duration(meta.get('eta_criteria'))}",
            ),
        )
    log = f"Log: {meta.get('log', 'none')}"
    if running and meta.get("log_fresh"):
        log = f"{log} ({meta['log_fresh']})"
    rows.append((_env_label(meta), "Keys: ? help / search : cmd"))
    rows.append((f"Path: {_clip_left(meta.get('case_path', ''), _BANNER_COLUMN_WIDTH - 6)}", log))
    return foam_style_banner("ofti", rows)


def _status_row(meta: dict[str, str], *, running: bool) -> tuple[str, str]:
    latest = meta.get("latest_time", "n/a")
    if not running:
        return f"Status: {meta.get('status', 'unknown')}", f"Latest time: {latest}"
    jobs = meta.get("jobs_running", "0")
    pids = meta.get("live_processes", "0")
    return f"Running: jobs={jobs} pids={pids}", f"Latest: {latest} iter={meta.get('latest_iteration', 'n/a')}"


def _env_label(meta: dict[str, str]) -> str:
    foam_version = meta.get("foam_version", "unknown")
    label = "Env: not loaded" if foam_version in ("", "unknown") else f"Env: {foam_version}"
    header_version = meta.get("case_header_version", "unknown")
    if header_version not in ("", "unknown", _FOAMFILE_FORMAT_VERSION, foam_version):
        label = f"{label} (case {header_version})"
    return label


def _mesh_label(meta: dict[str, str]) -> str:
    counts = [(meta.get("cells"), "cells"), (meta.get("faces"), "faces"), (meta.get("points"), "pts")]
    parts = [f"{_count(value)} {unit}" for value, unit in counts if value and value != "n/a"]
    if not parts:
        mesh = meta.get("mesh", "unknown")
        return f"Mesh: {'none' if mesh == 'unknown' else mesh}"
    label = "Mesh: " + " ".join(parts)
    # Points are the least useful count; drop them before clipping cells/faces.
    return label if len(label) <= _BANNER_COLUMN_WIDTH else "Mesh: " + " ".join(parts[:2])


def _quality_label(meta: dict[str, str]) -> str:
    mesh = meta.get("mesh", "unknown")
    quality = [part for part in mesh.split(", ") if part.startswith(_QUALITY_PREFIXES)]
    if quality:
        return "Quality: " + " ".join(quality)
    if mesh == "unknown":
        return "Quality: n/a"
    return "Quality: no checkMesh log"


def _count(value: str) -> str:
    try:
        number = int(value)
    except ValueError:
        return value
    for scale, suffix in _COUNT_UNITS:
        if number >= scale:
            return f"{number / scale:.1f}{suffix}"
    return str(number)


def _number(value: str | None) -> str:
    try:
        return f"{float(value):.3g}" if value not in (None, "") else "n/a"
    except (TypeError, ValueError):
        return str(value)


def _duration(value: str | None) -> str:
    try:
        seconds = float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return str(value)
    if seconds is None:
        return "n/a"
    total = round(seconds)
    if total < _SECONDS_PER_MINUTE:
        return f"{total}s"
    if total < _SECONDS_PER_HOUR:
        return f"{total // _SECONDS_PER_MINUTE}m{total % _SECONDS_PER_MINUTE:02d}s"
    return f"{total // _SECONDS_PER_HOUR}h{total % _SECONDS_PER_HOUR // _SECONDS_PER_MINUTE:02d}m"


def _clip_left(text: str, width: int) -> str:
    """Keep the informative tail of a path: ``/very/long/case`` -> ``...ng/case``."""
    return text if len(text) <= width else "..." + text[-(width - 3) :]


def foam_style_banner(label: str, rows: list[tuple[str, str]]) -> list[str]:
    # Rows are 79 columns wide; the frame matches so an 80-column terminal
    # (which cannot draw its last cell) shows both corners.
    inner = 2 * _BANNER_COLUMN_WIDTH + 3
    title = f"*- {label} -*"
    pad = (inner - len(title)) // 2
    top = "/*" + "-" * pad + title + "-" * (inner - len(title) - pad) + "*\\"
    bottom = "\\*" + "-" * inner + "*/"
    lines = [top]
    for left, right in rows:
        lines.append(format_banner_row(left, right))
    lines.append(bottom)
    return lines


def format_banner_row(left: str, right: str, column_width: int = _BANNER_COLUMN_WIDTH) -> str:
    def clip(text: str) -> str:
        return text[:column_width]

    return f"| {clip(left).ljust(column_width)} | {clip(right).ljust(column_width)} |"

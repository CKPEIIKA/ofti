from __future__ import annotations

import re
from math import sqrt
from pathlib import Path
from typing import Any

from ofti.tools.logs_analysis import _sparkline
from ofti.tools.runner import _show_message
from ofti.ui_curses.help import menu_hint
from ofti.ui_curses.menus import Menu
from ofti.ui_curses.viewer import Viewer


def probes_viewer_screen(stdscr: Any, case_path: Path) -> None:
    probes_root = case_path / "postProcessing" / "probes"
    if not probes_root.is_dir():
        _show_message(stdscr, "postProcessing/probes not found in case directory.")
        return

    candidates = [
        path
        for path in probes_root.rglob("*")
        if path.is_file() and path.name != "positions"
    ]
    if not candidates:
        _show_message(stdscr, "No probe files found under postProcessing/probes.")
        return

    labels = [p.relative_to(case_path).as_posix() for p in candidates]
    menu = Menu(
        stdscr,
        "Select probe file",
        [*labels, "Back"],
        hint_provider=lambda idx: (
            "Select probe data file."
            if 0 <= idx < len(labels)
            else menu_hint("menu:probes_select", "Back")
        ),
    )
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return

    path = candidates[choice]
    try:
        text = path.read_text(errors="ignore")
    except OSError as exc:
        _show_message(stdscr, f"Failed to read {path.name}: {exc}")
        return

    times, values, count = _parse_probe_series(text)
    if not values:
        _show_message(stdscr, f"No probe data found in {path.name}.")
        return

    _height, width = stdscr.getmaxyx()
    plot_width = max(10, min(50, width - 28))
    plot = _sparkline(values, plot_width)
    lines = [
        "Probes viewer",
        "",
        f"File: {path.relative_to(case_path).as_posix()}",
        f"Samples: {len(values)}",
        f"Probes per sample: {count} (showing first)",
        f"Time range: {times[0]:.3g} .. {times[-1]:.3g}" if times else "Time range: n/a",
        "",
        f"Value: {plot}",
        f"last={values[-1]:.3g} min={min(values):.3g} max={max(values):.3g}",
    ]
    Viewer(stdscr, "\n".join(lines)).display()


def _parse_probe_series(text: str) -> tuple[list[float], list[float], int]:
    times: list[float] = []
    values: list[float] = []
    probe_count = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("//", "#")):
            continue
        parsed = _parse_probe_line(line)
        if parsed is None:
            continue
        time, sample_values, count = parsed
        if not sample_values:
            continue
        times.append(time)
        values.append(sample_values[0])
        probe_count = count
    return times, values, probe_count


def _parse_probe_line(line: str) -> tuple[float, list[float], int] | None:
    parts = line.split(maxsplit=1)
    if not parts:
        return None
    try:
        time = float(parts[0])
    except ValueError:
        return None
    rest = parts[1] if len(parts) > 1 else ""
    values, count = _parse_probe_values(rest)
    if not values:
        return None
    return (time, values, count)


def _parse_probe_values(rest: str) -> tuple[list[float], int]:
    vectors = re.findall(r"\(([^)]+)\)", rest)
    if vectors:
        values_list: list[float] = []
        for vec in vectors:
            numbers = [float(val) for val in vec.split() if val]
            if numbers:
                magnitude = sqrt(sum(val * val for val in numbers))
                values_list.append(magnitude)
        if values_list:
            return values_list, len(values_list)
    floats = [float(val) for val in rest.split() if val]
    if floats:
        return floats, len(floats)
    return ([], 0)

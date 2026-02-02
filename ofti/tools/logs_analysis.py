from __future__ import annotations

from math import log10
from pathlib import Path
from typing import Any

from ofti.foamlib.logs import (
    execution_time_deltas,
    parse_courant_numbers,
    parse_execution_times,
    parse_log_metrics,
    parse_residuals,
    parse_time_steps,
)
from ofti.tools.logs_select import _select_solver_log_file
from ofti.tools.runner import _show_message
from ofti.ui_curses.viewer import Viewer


def residual_timeline_screen(stdscr: Any, case_path: Path) -> None:
    path = _select_solver_log_file(
        case_path,
        stdscr,
        title="Select solver log for residuals",
    )
    if path is None:
        return
    try:
        text = path.read_text()
    except OSError as exc:
        _show_message(stdscr, f"Failed to read {path.name}: {exc}")
        return

    residuals = parse_residuals(text)
    if not residuals:
        _show_message(stdscr, f"No residuals found in {path.name}.")
        return
    times = parse_time_steps(text)
    courants = parse_courant_numbers(text)
    exec_times = parse_execution_times(text)
    _height, width = stdscr.getmaxyx()
    plot_width = max(10, min(50, width - 28))
    lines = ["Residuals summary", ""]
    if times:
        lines.append(f"Time steps: {len(times)} (last={times[-1]:.6g})")
    if courants:
        lines.append(f"Max Courant: {max(courants):.6g}")
    if exec_times:
        lines.append(f"Execution time: {exec_times[-1]:.6g} s")
    if times or courants or exec_times:
        lines.append("")
    for field, values in sorted(residuals.items()):
        if not values:
            continue
        last = values[-1]
        min_val = min(values)
        max_val = max(values)
        plot = _sparkline(values, plot_width)
        lines.append(
            f"{field:>8} {plot} last={last:.3g} min={min_val:.3g} max={max_val:.3g}",
        )
    Viewer(stdscr, "\n".join(lines)).display()


def log_analysis_screen(stdscr: Any, case_path: Path) -> None:  # noqa: C901
    path = _select_solver_log_file(
        case_path,
        stdscr,
        title="Select solver log for analysis",
    )
    if path is None:
        return
    try:
        text = path.read_text()
    except OSError as exc:
        _show_message(stdscr, f"Failed to read {path.name}: {exc}")
        return

    metrics = parse_log_metrics(text)
    residuals = parse_residuals(text)
    if not (metrics.times or metrics.courants or metrics.execution_times or residuals):
        _show_message(stdscr, f"No metrics found in {path.name}.")
        return

    _height, width = stdscr.getmaxyx()
    plot_width = max(10, min(50, width - 28))

    lines = [
        "LOG ANALYSIS",
        "",
        f"File: {path.name}",
        "",
    ]
    if metrics.times:
        lines.append(f"Time steps: {len(metrics.times)} (last={metrics.times[-1]:.6g})")
    if metrics.courants:
        max_courant = max(metrics.courants)
        lines.append(f"Courant max: {max_courant:.6g}")
        lines.append(f"Courant trend: {_sparkline(metrics.courants, plot_width)}")
    if metrics.execution_times:
        deltas = execution_time_deltas(metrics.execution_times)
        lines.append(f"Execution time: {metrics.execution_times[-1]:.6g} s")
        if deltas:
            avg = sum(deltas) / len(deltas)
            lines.append(
                f"Step time: min={min(deltas):.6g} avg={avg:.6g} max={max(deltas):.6g}",
            )
            lines.append(f"Step trend: {_sparkline(deltas, plot_width)}")
    if residuals:
        lines.append("")
        lines.append("Residuals:")
        for field, values in sorted(residuals.items()):
            if not values:
                continue
            lines.append(
                f"- {field}: last={values[-1]:.3g} min={min(values):.3g} "
                f"max={max(values):.3g}",
            )

    Viewer(stdscr, "\n".join(lines)).display()


def _sparkline(values: list[float], width: int) -> str:
    if not values or width <= 0:
        return ""
    if len(values) <= width:
        sample = values
    else:
        step = len(values) / width
        sample = [values[int(i * step)] for i in range(width)]

    safe = [val if val > 0 else 1e-16 for val in sample]
    vmin = min(safe)
    vmax = max(safe)
    if vmax <= 0:
        vmax = 1e-16
    ratio = vmax / vmin if vmin > 0 else vmax
    if ratio > 1e3:
        scaled = [log10(val) for val in safe]
        vmin = min(scaled)
        vmax = max(scaled)
    else:
        scaled = safe

    levels = " .:-=+*#%@"
    span = vmax - vmin
    if span <= 0:
        return levels[-1] * len(sample)
    chars = []
    for val in scaled:
        norm = (val - vmin) / span
        idx = round(norm * (len(levels) - 1))
        idx = max(0, min(len(levels) - 1, idx))
        chars.append(levels[idx])
    return "".join(chars)

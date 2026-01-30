from __future__ import annotations

import curses
import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from math import log10, sqrt
from pathlib import Path
from typing import Any, cast

from ofti import foamlib_adapter
from ofti.core.case import (
    detect_mesh_stats,
    detect_parallel_settings,
    detect_solver,
    read_number_of_subdomains,
    set_start_from_latest,
)
from ofti.core.checkmesh import extract_last_courant, format_checkmesh_summary
from ofti.core.dict_compare import compare_case_dicts
from ofti.core.entry_io import list_subkeys, read_entry
from ofti.core.mesh_info import mesh_counts
from ofti.core.templates import write_example_template
from ofti.core.times import latest_time, time_directories
from ofti.core.tool_output import CommandResult, format_command_result, format_log_blob
from ofti.foam.config import get_config, key_hint, key_in
from ofti.foam.openfoam import OpenFOAMError
from ofti.foam.subprocess_utils import resolve_executable, run_trusted
from ofti.foamlib_adapter import available as foamlib_available
from ofti.foamlib_logs import (
    execution_time_deltas,
    parse_courant_numbers,
    parse_execution_times,
    parse_log_metrics,
    parse_residuals,
    parse_time_steps,
)
from ofti.foamlib_parametric import build_parametric_cases
from ofti.foamlib_runner import run_cases
from ofti.tools.helpers import (
    auto_detect_bashrc_paths,
    resolve_openfoam_bashrc,
    with_bashrc,
    wm_project_dir_from_bashrc,
)
from ofti.tools.runner import (
    _expand_shell_command,
    _maybe_job_hint,
    _no_foam_active,
    _normalize_tool_name,
    _record_tool_status,
    _run_shell_tool,
    _run_simple_tool,
    _show_message,
    _with_no_foam_hint,
    _write_tool_log,
    get_last_tool_run,
    last_tool_status_line,
    load_postprocessing_presets,
    load_tool_presets,
    tool_status_mode,
)
from ofti.ui_curses.help import diagnostics_help, tools_help
from ofti.ui_curses.high_speed import high_speed_helper_screen
from ofti.ui_curses.inputs import prompt_input
from ofti.ui_curses.layout import status_message
from ofti.ui_curses.menus import Menu
from ofti.ui_curses.viewer import Viewer


def run_tool_by_name(stdscr: Any, case_path: Path, name: str) -> bool:
    aliases = _tool_aliases(stdscr, case_path)
    key = _normalize_tool_name(name)
    handler = aliases.get(key)
    if handler is None:
        return False
    handler()
    return True


def _tool_aliases(stdscr: Any, case_path: Path) -> dict[str, Callable[[], None]]:
    aliases: dict[str, Callable[[], None]] = {}

    def add(name: str, handler: Callable[[], None]) -> None:
        aliases[_normalize_tool_name(name)] = handler

    def run_simple(name: str, cmd: list[str]) -> Callable[[], None]:
        return lambda: _run_simple_tool(stdscr, case_path, name, list(cmd))

    base_tools = [
        ("blockMesh", ["blockMesh"]),
        ("setFields", ["setFields"]),
        ("snappyHexMesh", ["snappyHexMesh"]),
        ("decomposePar", ["decomposePar"]),
        ("reconstructPar", ["reconstructPar"]),
        ("foamListTimes", ["foamListTimes"]),
    ]
    extra_tools = load_tool_presets(case_path)
    post_tools = load_postprocessing_presets(case_path)

    for name, cmd in base_tools + extra_tools:
        add(name, run_simple(name, cmd))

    for name, cmd in post_tools:
        add(name, run_simple(name, cmd))
        add(f"post.{name}", run_simple(name, cmd))
        add(f"post:{name}", run_simple(name, cmd))

    add("rerun", lambda: rerun_last_tool(stdscr, case_path))
    add("last", lambda: rerun_last_tool(stdscr, case_path))
    add("highspeed", lambda: high_speed_helper_screen(stdscr, case_path))
    add("high_speed", lambda: high_speed_helper_screen(stdscr, case_path))
    add("highspeedhelper", lambda: high_speed_helper_screen(stdscr, case_path))
    add("runscript", lambda: run_shell_script_screen(stdscr, case_path))
    add("postprocess", lambda: post_process_prompt(stdscr, case_path))
    add("foamcalc", lambda: foam_calc_prompt(stdscr, case_path))
    add("runcurrentsolver", lambda: run_current_solver(stdscr, case_path))
    add("runlive", lambda: run_current_solver_live(stdscr, case_path))
    add("removelogs", lambda: remove_all_logs(stdscr, case_path))
    add("cleantimedirs", lambda: clean_time_directories(stdscr, case_path))
    add("cleancase", lambda: clean_case(stdscr, case_path))
    add("blockmesh", lambda: run_blockmesh(stdscr, case_path))
    add("decomposepar", lambda: run_decomposepar(stdscr, case_path))
    add("reconstruct_manager", lambda: reconstruct_manager_screen(stdscr, case_path))
    add("reconstructmanager", lambda: reconstruct_manager_screen(stdscr, case_path))
    add("timedir_pruner", lambda: time_directory_pruner_screen(stdscr, case_path))
    add("timedirpruner", lambda: time_directory_pruner_screen(stdscr, case_path))
    add("safestop", lambda: safe_stop_screen(stdscr, case_path))
    add("solveresume", lambda: solver_resurrection_screen(stdscr, case_path))
    add("clone", lambda: clone_case(stdscr, case_path))
    add("yplus", lambda: yplus_screen(stdscr, case_path))
    add("checkmesh", lambda: run_checkmesh(stdscr, case_path))
    add("logs", lambda: logs_screen(stdscr, case_path))
    add("viewlogs", lambda: logs_screen(stdscr, case_path))
    add("residuals", lambda: residual_timeline_screen(stdscr, case_path))
    add("residual_timeline", lambda: residual_timeline_screen(stdscr, case_path))
    add("probes", lambda: probes_viewer_screen(stdscr, case_path))
    add("probesviewer", lambda: probes_viewer_screen(stdscr, case_path))

    return aliases


def tools_screen(stdscr: Any, case_path: Path) -> None:  # noqa: C901, PLR0912
    """
    Tools menu with common solvers/utilities, job helpers, logs, and
    optional shell scripts, all in a single flat list.
    """
    base_tools = [
    ]
    extra_tools = load_tool_presets(case_path)
    post_tools = [
        (f"[post] {name}", cmd) for name, cmd in load_postprocessing_presets(case_path)
    ]

    simple_tools = base_tools + extra_tools + post_tools

    labels = ["Re-run last tool"] + [name for name, _ in simple_tools] + [
        "Diagnostics",
        "High-speed initial conditions",
        "yPlus estimator",
        "Run .sh script",
        "Clone case",
    ]

    def hint_for(idx: int) -> str:
        if idx == 0:
            last = get_last_tool_run()
            if last is None:
                base = "Re-run last tool (none yet)"
            else:
                base = f"Re-run last tool: {last.name}"
            return f"{base} | {tool_status_mode()}"
        simple_index = idx - 1
        if 0 <= simple_index < len(simple_tools):
            name, _cmd = simple_tools[simple_index]
            if name.startswith("[post]"):
                return f"Post-processing preset: {name} | {tool_status_mode()}"
            return f"Run tool: {name} | {tool_status_mode()}"
        special = idx - 1 - len(simple_tools)
        hints = [
            "Environment and installation checks",
            "Compute U/p0 from Mach + T + gamma",
            "Estimate yPlus from case mesh/logs",
            "Run a shell script from case folder",
            "Clone case directory and clean mesh/time/logs",
        ]
        if 0 <= special < len(hints):
            return f"{hints[special]} | {tool_status_mode()}"
        return ""

    disabled = set(range(len(labels))) if _no_foam_active() else None
    status_line = (
        "Limited mode: OpenFOAM env not found (simple editor only)"
        if _no_foam_active()
        else None
    )
    last_status = last_tool_status_line()
    if last_status:
        status_line = f"{status_line} | {last_status}" if status_line else last_status
    menu = Menu(
        stdscr,
        "Tools",
        [*labels, "Back"],
        hint_provider=hint_for,
        status_line=status_line,
        disabled_indices=disabled,
        help_lines=tools_help(),
    )
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return

    # Simple tools segment.
    if choice == 0:
        rerun_last_tool(stdscr, case_path)
        return
    simple_index = choice - 1
    if simple_index < len(simple_tools):
        name, cmd = simple_tools[simple_index]
        _run_simple_tool(stdscr, case_path, name, cmd)
        return

    # Offsets into special actions.
    special_index = choice - 1 - len(simple_tools)
    if special_index == 0:
        diagnostics_screen(stdscr, case_path)
    elif special_index == 1:
        high_speed_helper_screen(stdscr, case_path)
    elif special_index == 2:
        yplus_screen(stdscr, case_path)
    elif special_index == 3:
        job_status_poll_screen(stdscr, case_path)
    elif special_index == 4:
        run_shell_script_screen(stdscr, case_path)
    elif special_index == 5:
        foam_dictionary_prompt(stdscr, case_path)
    elif special_index == 6:
        topo_set_prompt(stdscr, case_path)
    elif special_index == 7:
        set_fields_prompt(stdscr, case_path)
    elif special_index == 8:
        tool_dicts_screen(stdscr, case_path)
    elif special_index == 9:
        clone_case(stdscr, case_path)


def logs_screen(stdscr: Any, case_path: Path) -> None:
    """
    Simple log viewer for files matching log.* in the case directory.
    """
    while True:
        path = _select_log_file(case_path, stdscr)
        if path is None:
            return
        try:
            text = path.read_text()
        except OSError as exc:
            _show_message(stdscr, f"Failed to read {path.name}: {exc}")
            continue

        viewer = Viewer(stdscr, text)
        viewer.display()


def open_paraview_screen(stdscr: Any, case_path: Path) -> None:
    foam_file = case_path / f"{case_path.name}.foam"
    try:
        foam_file.write_text("")
    except OSError as exc:
        _show_message(stdscr, f"Failed to create {foam_file.name}: {exc}")
        return

    resolved = shutil.which("paraview")
    if not resolved:
        _show_message(
            stdscr,
            f"Created {foam_file.name}. paraview not found on PATH.",
        )
        return
    curses.endwin()
    try:
        run_trusted([resolved, str(foam_file)], capture_output=False, check=False)
    finally:
        stdscr.clear()
        stdscr.refresh()


def residual_timeline_screen(stdscr: Any, case_path: Path) -> None:
    """
    Parse residuals from a selected log file and show a summary table + plot.
    """
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
    """
    Summarize common log metrics (time steps, Courant, execution time).
    """
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

    # Log-scale if range is large, but keep zeros safe.
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


def _tail_text(text: str, max_lines: int = 20) -> str:
    lines = text.strip().splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines) if lines else "(empty)"
    tail = "\n".join(lines[-max_lines:])
    return f"... ({len(lines) - max_lines} lines omitted)\n{tail}"


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
    menu = Menu(stdscr, "Select probe file", [*labels, "Back"])
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


def postprocessing_browser_screen(stdscr: Any, case_path: Path) -> None:
    root = case_path / "postProcessing"
    if not root.is_dir():
        _show_message(stdscr, "postProcessing directory not found.")
        return
    files = _collect_postprocessing_files(root)
    if not files:
        _show_message(stdscr, "No postProcessing files found.")
        return
    labels = ["Summary"] + [p.relative_to(case_path).as_posix() for p in files] + ["Back"]
    menu = Menu(stdscr, "PostProcessing browser", labels)
    choice = menu.navigate()
    if choice == -1 or choice == len(labels) - 1:
        return
    if choice == 0:
        lines = _postprocessing_summary(root)
        Viewer(stdscr, "\n".join(lines)).display()
        return
    path = files[choice - 1]
    try:
        text = path.read_text(errors="ignore")
    except OSError as exc:
        _show_message(stdscr, f"Failed to read {path.name}: {exc}")
        return
    Viewer(stdscr, text).display()


def sampling_sets_screen(stdscr: Any, case_path: Path) -> None:
    options = _sampling_options(case_path)
    labels = [opt.label for opt in options] + ["Back"]
    disabled = {idx for idx, opt in enumerate(options) if not opt.enabled}
    menu = Menu(stdscr, "Sampling & sets", labels, disabled_indices=disabled)
    choice = menu.navigate()
    if choice == -1 or choice == len(labels) - 1:
        return
    opt = options[choice]
    if not opt.enabled:
        _show_message(stdscr, f"Missing {opt.required_path}.")
        return
    status_message(stdscr, f"Running {opt.label}...")
    try:
        result = run_trusted(
            opt.command,
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run {opt.label}: {exc}"))
        return
    summary = format_command_result(
        [f"$ cd {case_path}", f"$ {' '.join(opt.command)}"],
        CommandResult(result.returncode, result.stdout, result.stderr),
    )
    Viewer(stdscr, summary).display()


def parametric_presets_screen(stdscr: Any, case_path: Path) -> None:
    presets_path = case_path / "ofti.parametric"
    if not presets_path.is_file():
        _show_message(stdscr, "ofti.parametric not found in case directory.")
        return
    presets, errors = _read_parametric_presets(presets_path)
    if errors:
        lines = ["PARAMETRIC PRESET ERRORS", "", *errors]
        Viewer(stdscr, "\n".join(lines)).display()
        return
    if not presets:
        _show_message(stdscr, "No presets found in ofti.parametric.")
        return
    labels = [preset.name for preset in presets] + ["Back"]
    menu = Menu(stdscr, "Parametric presets", labels)
    choice = menu.navigate()
    if choice == -1 or choice == len(labels) - 1:
        return
    preset = presets[choice]
    run_line = _prompt_line(stdscr, "Run solver for each case? [y/N]: ")
    run_solver = run_line.strip().lower().startswith("y")
    try:
        created = build_parametric_cases(
            case_path,
            Path(preset.dict_path),
            preset.entry,
            preset.values,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _show_message(stdscr, f"Parametric setup failed: {exc}")
        return

    failures: list[Path] = []
    if run_solver:
        failures = run_cases(created, check=False)

    lines = [
        f"Preset: {preset.name}",
        f"Created {len(created)} case(s):",
        *[f"- {path}" for path in created],
    ]
    if run_solver:
        if failures:
            lines += ["", "Failures:", *[f"- {path}" for path in failures]]
        else:
            lines += ["", "All cases completed."]
    Viewer(stdscr, "\n".join(lines)).display()


def field_summary_screen(stdscr: Any, case_path: Path) -> None:
    time_dir = _latest_time_dir(case_path)
    if time_dir is None:
        _show_message(stdscr, "No time directories found.")
        return
    files = sorted(p for p in time_dir.iterdir() if p.is_file())
    if not files:
        _show_message(stdscr, f"No field files found in {time_dir.name}.")
        return
    labels = [p.name for p in files]
    menu = Menu(stdscr, f"Select field ({time_dir.name})", [*labels, "Back"])
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return
    path = files[choice]
    lines = _field_summary_lines(case_path, path)
    Viewer(stdscr, "\n".join(lines)).display()


def _collect_postprocessing_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def _postprocessing_summary(root: Path) -> list[str]:
    lines = ["POSTPROCESSING SUMMARY", "", f"Root: {root}", ""]
    for subdir in sorted(p for p in root.iterdir() if p.is_dir()):
        time_dirs = [
            d
            for d in subdir.iterdir()
            if d.is_dir() and _looks_like_time(d.name)
        ]
        files = [p for p in subdir.rglob("*") if p.is_file()]
        lines.append(
            f"{subdir.name}: times={len(time_dirs)} files={len(files)}",
        )
    if len(lines) == 4:
        lines.append("(no postProcessing subdirectories)")
    return lines


def _looks_like_time(name: str) -> bool:
    try:
        float(name)
    except ValueError:
        return False
    return True


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
    menu = Menu(stdscr, title, [*labels, "Back"])
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
    menu = Menu(stdscr, title, [*labels, "Back"])
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return None
    return log_files[choice]


@dataclass(frozen=True)
class ParametricPreset:
    name: str
    dict_path: str
    entry: str
    values: list[str]


def _read_parametric_presets(path: Path) -> tuple[list[ParametricPreset], list[str]]:
    presets: list[ParametricPreset] = []
    errors: list[str] = []
    try:
        lines = path.read_text(errors="ignore").splitlines()
    except OSError as exc:
        return [], [f"Failed to read {path.name}: {exc}"]
    for line_no, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            parts = [part.strip() for part in line.split("|")]
            if len(parts) != 4:
                errors.append(f"Line {line_no}: expected 4 fields separated by |")
                continue
            name, dict_path, entry, values_raw = parts
        elif ":" in line:
            name_part, rest = line.split(":", 1)
            tokens = rest.strip().split()
            if len(tokens) < 2:
                errors.append(f"Line {line_no}: expected '<dict> <entry> <values>'")
                continue
            name = name_part.strip()
            dict_path = tokens[0]
            entry = tokens[1]
            values_raw = " ".join(tokens[2:]) if len(tokens) > 2 else ""
        else:
            errors.append(f"Line {line_no}: expected 'name | dict | entry | values'")
            continue
        values = [val.strip() for val in values_raw.split(",") if val.strip()]
        if not (name and dict_path and entry and values):
            errors.append(f"Line {line_no}: missing name, dict, entry, or values")
            continue
        presets.append(ParametricPreset(name, dict_path, entry, values))
    return presets, errors


@dataclass(frozen=True)
class SamplingOption:
    label: str
    command: list[str]
    required_path: Path
    enabled: bool


def _sampling_options(case_path: Path) -> list[SamplingOption]:
    topo = case_path / "system" / "topoSetDict"
    sample = case_path / "system" / "sampleDict"
    dist = case_path / "system" / "distributionDict"
    return [
        SamplingOption("Run topoSet", ["topoSet"], topo, topo.is_file()),
        SamplingOption(
            "Run sample (postProcess -func sample)",
            ["postProcess", "-func", "sample"],
            sample,
            sample.is_file(),
        ),
        SamplingOption(
            "Run distribution (postProcess -func distribution)",
            ["postProcess", "-func", "distribution"],
            dist,
            dist.is_file(),
        ),
    ]


def _latest_time_dir(case_path: Path) -> Path | None:
    latest = latest_time(case_path)
    if not latest:
        return None
    time_dir = case_path / latest
    if time_dir.is_dir():
        return time_dir
    return None


def _field_summary_lines(case_path: Path, field_path: Path) -> list[str]:
    rel = field_path.relative_to(case_path).as_posix()
    lines = ["FIELD SUMMARY", "", f"File: {rel}", ""]
    if not (foamlib_adapter.available() and foamlib_adapter.is_foam_file(field_path)):
        lines.append("foamlib not available or file not recognized.")
        return lines
    try:
        klass = foamlib_adapter.read_entry_node(field_path, "FoamFile.class")
    except Exception:
        klass = None
    try:
        obj = foamlib_adapter.read_entry_node(field_path, "FoamFile.object")
    except Exception:
        obj = None
    if klass:
        lines.append(f"Class: {klass}")
    if obj:
        lines.append(f"Object: {obj}")
    lines.append("")

    internal = _read_optional_node(field_path, "internalField")
    lines.extend(_summarize_internal_field(internal))

    patches = foamlib_adapter.list_subkeys(field_path, "boundaryField")
    if patches:
        lines.append(f"Boundary patches: {len(patches)}")
    else:
        lines.append("Boundary patches: none")
    return lines


def _read_optional_node(field_path: Path, key: str) -> object | None:
    try:
        return foamlib_adapter.read_entry_node(field_path, key)
    except Exception:
        return None


def _summarize_internal_field(node: object | None) -> list[str]:  # noqa: PLR0911
    if node is None:
        return ["Internal field: <missing>"]
    if isinstance(node, (int, float, bool)):
        return [f"Internal field: {node}"]
    if isinstance(node, str):
        return [f"Internal field: {node.strip()}"]
    if isinstance(node, (list, tuple)):
        return _summarize_sequence(cast(list[object] | tuple[object, ...], node))
    if hasattr(node, "shape"):
        try:
            size = int(getattr(node, "size", 0))
            if size <= 0:
                return [f"Internal field: array shape={getattr(node, 'shape', '')}"]
            return _summarize_array(node)
        except Exception:
            return [f"Internal field: array shape={getattr(node, 'shape', '')}"]
    return [f"Internal field: {type(node).__name__}"]


def _summarize_sequence(values: list[object] | tuple[object, ...]) -> list[str]:
    floats: list[float] = []
    for value in values:
        if isinstance(value, (int, float)):
            floats.append(float(value))
            continue
        with suppress(Exception):
            floats.append(float(str(value)))
    if not floats:
        return [f"Internal field: list ({len(values)})"]
    return [f"Internal field: vector {floats}"]


def _summarize_array(node: object) -> list[str]:
    astype = getattr(node, "astype", None)
    if not callable(astype):
        return [f"Internal field: array shape={getattr(node, 'shape', '')}"]
    try:
        values = astype(float)
    except Exception:
        return [f"Internal field: array shape={getattr(node, 'shape', '')}"]
    min_fn = getattr(values, "min", None)
    max_fn = getattr(values, "max", None)
    if not callable(min_fn) or not callable(max_fn):
        return [f"Internal field: array shape={getattr(values, 'shape', '')}"]
    try:
        min_val = float(min_fn())
        max_val = float(max_fn())
    except Exception:
        return [f"Internal field: array shape={getattr(values, 'shape', '')}"]
    shape = getattr(values, "shape", "")
    return [f"Internal field: array shape={shape} min={min_val:.6g} max={max_val:.6g}"]


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
        return values_list, len(values_list)

    floats: list[float] = []
    for token in rest.split():
        try:
            floats.append(float(token))
        except ValueError:
            continue
    return floats, len(floats)


def job_status_poll_screen(stdscr: Any, case_path: Path) -> None:  # noqa: C901
    """
    Poll foamCheckJobs/foamPrintJobs until the user quits.
    """
    stdscr.timeout(500)
    try:
        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()
            back_hint = key_hint("back", "h")
            header = f"Job status ({back_hint} to exit)"
            with suppress(curses.error):
                stdscr.addstr(header[: max(1, width - 1)] + "\n")

            hint = _maybe_job_hint("foamPrintJobs")
            if hint:
                with suppress(curses.error):
                    stdscr.addstr(hint[: max(1, width - 1)] + "\n\n")
            else:
                with suppress(curses.error):
                    stdscr.addstr("\n")

            output_lines: list[str] = []
            for tool in ("foamCheckJobs", "foamPrintJobs"):
                try:
                    result = run_trusted(
                        [tool],
                        cwd=case_path,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                except OSError as exc:
                    output_lines.append(f"{tool}: failed: {exc}")
                    continue
                output_lines.append(f"{tool} (exit {result.returncode})")
                output_lines.extend((result.stdout or "").splitlines())

            for line in output_lines:
                if stdscr.getyx()[0] >= height - 2:
                    break
                try:
                    stdscr.addstr(line[: max(1, width - 1)] + "\n")
                except curses.error:
                    break

            stdscr.refresh()
            key = stdscr.getch()
            if key in (ord("q"), ord("h")):
                return
            if key_in(key, get_config().keys.get("quit", [])):
                return
            if key_in(key, get_config().keys.get("back", [])):
                return
    finally:
        stdscr.timeout(-1)


def run_shell_script_screen(stdscr: Any, case_path: Path) -> None:
    """
    Discover and run *.sh scripts in the case directory.

    Scripts are executed with the case directory as the current working
    directory, and their output is captured and shown in a viewer.
    """
    scripts = sorted(p for p in case_path.glob("*.sh") if p.is_file())
    if not scripts:
        _show_message(stdscr, "No *.sh scripts found in case directory.")
        return

    labels = [p.name for p in scripts]
    menu = Menu(stdscr, "Select script to run", [*labels, "Back"])
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return

    path = scripts[choice]
    status_message(stdscr, f"Running {path.name}...")
    try:
        result = run_trusted(
            ["sh", str(path)],
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _show_message(stdscr, f"Failed to run {path.name}: {exc}")
        return

    summary = format_command_result(
        [f"$ cd {case_path}", f"$ sh {path.name}"],
        CommandResult(result.returncode, result.stdout, result.stderr),
    )
    viewer = Viewer(stdscr, summary)
    viewer.display()


def rerun_last_tool(stdscr: Any, case_path: Path) -> None:
    last = get_last_tool_run()
    if last is None:
        _show_message(stdscr, "No previous tool run recorded.")
        return
    if last.kind == "shell":
        _run_shell_tool(stdscr, case_path, f"Re-run {last.name}", str(last.command))
    else:
        _run_simple_tool(stdscr, case_path, f"Re-run {last.name}", list(last.command))


def foam_dictionary_prompt(stdscr: Any, case_path: Path) -> None:
    """
    Prompt for a dictionary file and optional arguments to pass to foamDictionary.
    """
    stdscr.clear()
    path_input = prompt_input(
        stdscr,
        "Relative path to dictionary (default system/controlDict): ",
    )
    if path_input is None:
        return
    path_input = path_input.strip()
    if not path_input:
        path_input = "system/controlDict"

    dictionary_path = (case_path / path_input).resolve()
    if not dictionary_path.is_file():
        _show_message(stdscr, f"{dictionary_path} not found.")
        return

    args_line = prompt_input(stdscr, "foamDictionary args (e.g. -entry application): ")
    if args_line is None:
        return
    args_line = args_line.strip()

    try:
        args = shlex.split(args_line) if args_line else []
    except ValueError as exc:
        _show_message(stdscr, f"Invalid arguments: {exc}")
        return

    cmd = ["foamDictionary", str(dictionary_path), *args]
    try:
        result = run_trusted(
            cmd,
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run foamDictionary: {exc}"))
        return

    summary = format_command_result(
        [f"$ cd {case_path}", f"$ {' '.join(cmd)}"],
        CommandResult(result.returncode, result.stdout, result.stderr),
    )
    viewer = Viewer(stdscr, summary)
    viewer.display()


def post_process_prompt(stdscr: Any, case_path: Path) -> None:  # noqa: C901
    """
    Prompt for postProcess arguments, suggesting use of latestTime.
    """
    latest = latest_time(case_path)
    if not _ensure_tool_dict(
        stdscr,
        case_path,
        "postProcess",
        case_path / "system" / "postProcessDict",
        ["postProcess", "-list"],
    ):
        return
    while True:
        options = [
            "Run with defaults (-latestTime)",
            "Select function from postProcessDict",
            "Enter args manually",
            "Back",
        ]
        menu = Menu(
            stdscr,
            "postProcess",
            options,
            status_line=f"Latest time: {latest}",
        )
        choice = menu.navigate()
        if choice in (-1, len(options) - 1):
            return
        if choice == 0:
            _run_simple_tool(stdscr, case_path, "postProcess", ["postProcess", "-latestTime"])
            return
        if choice == 1:
            dict_path = case_path / "system" / "postProcessDict"
            funcs = list_subkeys(dict_path, "functions")
            if not funcs:
                _show_message(stdscr, "No functions found in postProcessDict.")
                continue
            func_menu = Menu(stdscr, "Select postProcess function", [*funcs, "Back"])
            func_choice = func_menu.navigate()
            if func_choice in (-1, len(funcs)):
                continue
            func = funcs[func_choice]
            cmd = ["postProcess", "-latestTime", "-funcs", f"({func})"]
            _run_simple_tool(stdscr, case_path, "postProcess", cmd)
            return
        if choice == 2:
            stdscr.clear()
            stdscr.addstr("postProcess args (e.g. -latestTime -funcs '(mag(U))'):\n")
            stdscr.addstr(f"Tip: latest time detected = {latest}\n")
            args_line = prompt_input(stdscr, "> ")
            if args_line is None:
                return
            args_line = args_line.strip()
            try:
                args = shlex.split(args_line) if args_line else ["-latestTime"]
            except ValueError as exc:
                _show_message(stdscr, f"Invalid arguments: {exc}")
                continue
            cmd = ["postProcess", *args]
            _run_simple_tool(stdscr, case_path, "postProcess", cmd)
            return


def foam_calc_prompt(stdscr: Any, case_path: Path) -> None:  # noqa: C901, PLR0912
    """
    Prompt for foamCalc arguments with helpers.
    """
    latest = latest_time(case_path)
    if not _ensure_tool_dict(
        stdscr,
        case_path,
        "foamCalc",
        case_path / "system" / "foamCalcDict",
        ["foamCalc", "-help"],
    ):
        return
    while True:
        options = [
            "Run with foamCalcDict",
            "Common ops (mag/grad/div)",
            "Enter args manually",
            "Back",
        ]
        menu = Menu(
            stdscr,
            "foamCalc",
            options,
            status_line=f"Latest time: {latest}",
        )
        choice = menu.navigate()
        if choice in (-1, len(options) - 1):
            return
        if choice == 0:
            _run_simple_tool(stdscr, case_path, "foamCalc", ["foamCalc"])
            return
        if choice == 1:
            ops = ["mag", "grad", "div", "Back"]
            op_menu = Menu(stdscr, "foamCalc common ops", ops)
            op_choice = op_menu.navigate()
            if op_choice == -1 or op_choice == len(ops) - 1:
                continue
            op = ops[op_choice]
            field = prompt_input(stdscr, f"{op} field (default U): ")
            if field is None:
                continue
            field = field.strip() or "U"
            cmd = ["foamCalc", op, field, "-latestTime"]
            if op == "div":
                flux = prompt_input(stdscr, "div flux field (default phi): ")
                if flux is None:
                    continue
                flux = flux.strip() or "phi"
                cmd = ["foamCalc", op, flux, field, "-latestTime"]
            _run_simple_tool(stdscr, case_path, f"foamCalc {op}", cmd)
            return
        if choice == 2:
            stdscr.clear()
            stdscr.addstr("foamCalc args (e.g. components U -latestTime):\n")
            stdscr.addstr(f"Tip: latest time detected = {latest}\n")
            args_line = prompt_input(stdscr, "> ")
            if args_line is None:
                return
            args_line = args_line.strip()
            if not args_line:
                _show_message(stdscr, "No arguments provided for foamCalc.")
                continue
            try:
                args = shlex.split(args_line)
            except ValueError as exc:
                _show_message(stdscr, f"Invalid arguments: {exc}")
                continue
            cmd = ["foamCalc", *args]
            _run_simple_tool(stdscr, case_path, "foamCalc", cmd)
            return


def topo_set_prompt(stdscr: Any, case_path: Path) -> None:
    """
    Prompt for topoSet arguments.
    """
    if not _ensure_tool_dict(
        stdscr,
        case_path,
        "topoSet",
        case_path / "system" / "topoSetDict",
        ["topoSetDict"],
    ):
        return
    stdscr.clear()
    stdscr.addstr("topoSet args (press Enter to run with defaults):\n")
    args_line = prompt_input(stdscr, "> ")
    if args_line is None:
        return
    args_line = args_line.strip()

    try:
        args = shlex.split(args_line) if args_line else []
    except ValueError as exc:
        _show_message(stdscr, f"Invalid arguments: {exc}")
        return

    cmd = ["topoSet", *args]
    _run_simple_tool(stdscr, case_path, "topoSet", cmd)


def set_fields_prompt(stdscr: Any, case_path: Path) -> None:
    """
    Prompt for setFields arguments.
    """
    if not _ensure_tool_dict(
        stdscr,
        case_path,
        "setFields",
        case_path / "system" / "setFieldsDict",
        None,
    ):
        return
    stdscr.clear()
    stdscr.addstr("setFields args (press Enter to run with defaults):\n")
    args_line = prompt_input(stdscr, "> ")
    if args_line is None:
        return
    args_line = args_line.strip()

    try:
        args = shlex.split(args_line) if args_line else []
    except ValueError as exc:
        _show_message(stdscr, f"Invalid arguments: {exc}")
        return

    cmd = ["setFields", *args]
    _run_simple_tool(stdscr, case_path, "setFields", cmd)


def _require_wm_project_dir(stdscr: Any) -> str | None:
    wm_dir = os.environ.get("WM_PROJECT_DIR")
    if not wm_dir:
        bashrc = resolve_openfoam_bashrc()
        if bashrc:
            derived = wm_project_dir_from_bashrc(bashrc)
            if derived:
                os.environ["WM_PROJECT_DIR"] = derived
                return derived
        candidates = auto_detect_bashrc_paths()
        suggestion = ""
        if candidates:
            preview = "\n".join(f"- {path}" for path in candidates[:5])
            suggestion = (
                "\nDetected OpenFOAM bashrc files:\n"
                f"{preview}\n"
                "Use :foamenv to select one or set OFTI_BASHRC."
            )
        _show_message(
            stdscr,
            _with_no_foam_hint(
                "WM_PROJECT_DIR is not set. Please source your OpenFOAM environment first."
                f"{suggestion}",
            ),
        )
        return None
    return wm_dir




def run_current_solver(stdscr: Any, case_path: Path) -> None:
    """
    Determine the solver from system/controlDict and run it via
    runApplication (RunFunctions).
    """
    control_dict = case_path / "system" / "controlDict"
    if not control_dict.is_file():
        _show_message(stdscr, "system/controlDict not found in case directory.")
        return

    try:
        value = read_entry(control_dict, "application")
    except OpenFOAMError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to read application: {exc}"))
        return

    solver_line = value.strip()
    if not solver_line:
        _show_message(stdscr, "application entry is empty.")
        return

    solver = solver_line.split()[0].rstrip(";")
    if not solver:
        _show_message(stdscr, "Could not determine solver from application entry.")
        return

    _run_simple_tool(stdscr, case_path, solver, [solver], allow_runfunctions=False)


def run_current_solver_live(stdscr: Any, case_path: Path) -> None:  # noqa: PLR0911
    """
    Run the solver and tail its log file live with a split-screen view.
    """
    control_dict = case_path / "system" / "controlDict"
    if not control_dict.is_file():
        _show_message(stdscr, "system/controlDict not found in case directory.")
        return

    try:
        value = read_entry(control_dict, "application")
    except OpenFOAMError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to read application: {exc}"))
        return

    solver_line = value.strip()
    if not solver_line:
        _show_message(stdscr, "application entry is empty.")
        return

    solver = solver_line.split()[0].rstrip(";")
    if not solver:
        _show_message(stdscr, "Could not determine solver from application entry.")
        return

    log_path = case_path / f"log.{solver}"
    if log_path.exists():
        stdscr.clear()
        stdscr.addstr(f"Log {log_path.name} already exists. Rerun solver? [y/N]: ")
        stdscr.refresh()
        ch = stdscr.getch()
        if ch not in (ord("y"), ord("Y")):
            return
        with suppress(OSError):
            log_path.unlink()

    wm_dir = _require_wm_project_dir(stdscr)
    if wm_dir and get_config().use_runfunctions:
        cmd_str = shlex.quote(solver)
        shell_cmd = f'. "{wm_dir}/bin/tools/RunFunctions"; runApplication {cmd_str}'
        _run_solver_live_shell(stdscr, case_path, solver, shell_cmd)
        return

    bashrc = resolve_openfoam_bashrc()
    if bashrc:
        shell_cmd = solver
        _run_solver_live_shell(stdscr, case_path, solver, shell_cmd)
        return

    _run_solver_live_cmd(stdscr, case_path, solver, [solver])


def _run_solver_live_shell(stdscr: Any, case_path: Path, solver: str, shell_cmd: str) -> None:
    command = with_bashrc(_expand_shell_command(shell_cmd, case_path))
    env = os.environ.copy()
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)
    log_path = case_path / f"log.{solver}"
    with suppress(OSError):
        log_path.write_text("")
    with log_path.open("a", encoding="utf-8", errors="ignore") as handle:
        try:
            bash_path = resolve_executable("bash")
        except FileNotFoundError as exc:
            _show_message(stdscr, _with_no_foam_hint(f"Failed to run {solver}: {exc}"))
            return
        process = subprocess.Popen(  # noqa: S603
            [bash_path, "--noprofile", "--norc", "-c", command],
            cwd=case_path,
            stdout=handle,
            stderr=handle,
            text=True,
            env=env,
        )
        _tail_process_log(stdscr, solver, process, log_path)


def _run_solver_live_cmd(
    stdscr: Any,
    case_path: Path,
    solver: str,
    cmd: list[str],
) -> None:
    log_path = case_path / f"log.{solver}"
    with suppress(OSError):
        log_path.write_text("")
    with log_path.open("a", encoding="utf-8", errors="ignore") as handle:
        process = subprocess.Popen(  # noqa: S603
            cmd,
            cwd=case_path,
            stdout=handle,
            stderr=handle,
            text=True,
        )
        _tail_process_log(stdscr, solver, process, log_path)


def _tail_process_log(  # noqa: C901, PLR0912
    stdscr: Any,
    solver: str,
    process: subprocess.Popen[str],
    log_path: Path,
) -> None:
    cfg = get_config()
    patterns = ["FATAL", "bounding", "Courant", "nan", "SIGFPE", "floating point exception"]
    stdscr.timeout(400)
    try:
        while True:
            try:
                text = log_path.read_text(errors="ignore")
            except OSError:
                text = ""
            lines = text.splitlines()
            tail = lines[-12:]
            last_time = _extract_last_time(lines)
            last_courant = extract_last_courant(lines)

            stdscr.clear()
            height, width = stdscr.getmaxyx()
            back_hint = key_hint("back", "h")
            status = "running" if process.poll() is None else "finished"
            header = f"{solver} ({status})  {back_hint}: stop"
            with suppress(curses.error):
                stdscr.addstr(header[: max(1, width - 1)] + "\n")
            summary = ""
            if last_time is not None:
                summary = f"Time = {last_time}"
            if last_courant is not None:
                if summary:
                    summary = f"{summary} | Courant: {last_courant:g}"
                else:
                    summary = f"Courant: {last_courant:g}"
            if summary:
                with suppress(curses.error):
                    stdscr.addstr(summary[: max(1, width - 1)] + "\n")
            with suppress(curses.error):
                stdscr.addstr("-" * max(1, width - 1) + "\n")

            for line in tail:
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
            if process.poll() is not None:
                stdscr.timeout(-1)
                stdscr.getch()
                return
            key = stdscr.getch()
            if key_in(key, cfg.keys.get("back", [])):
                process.terminate()
                process.wait(timeout=5)
                return
    finally:
        stdscr.timeout(-1)


def _extract_last_time(lines: list[str]) -> str | None:
    for line in reversed(lines):
        if "Time =" in line:
            parts = line.split("Time =", 1)
            if len(parts) == 2:
                return parts[1].strip().split()[0]
    return None


def remove_all_logs(
    stdscr: Any,
    case_path: Path,
    *,
    silent: bool = False,
    use_cleanfunctions: bool = True,
) -> None:
    """
    Remove log.* files using CleanFunctions helpers.
    """
    wm_dir = _require_wm_project_dir(stdscr) if use_cleanfunctions else None
    if use_cleanfunctions and wm_dir and get_config().use_cleanfunctions:
        shell_cmd = f'. "{wm_dir}/bin/tools/CleanFunctions"; cleanApplicationLogs'
        _run_shell_tool(stdscr, case_path, "cleanApplicationLogs", shell_cmd)
        return

    removed = 0
    for path in case_path.glob("log.*"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    if not silent:
        _show_message(stdscr, f"Removed {removed} log files.")


def clean_time_directories(
    stdscr: Any,
    case_path: Path,
    *,
    silent: bool = False,
    use_cleanfunctions: bool = True,
) -> None:
    """
    Remove time directories using CleanFunctions.
    """
    wm_dir = _require_wm_project_dir(stdscr) if use_cleanfunctions else None
    if use_cleanfunctions and wm_dir and get_config().use_cleanfunctions:
        shell_cmd = f'. "{wm_dir}/bin/tools/CleanFunctions"; cleanTimeDirectories'
        _run_shell_tool(stdscr, case_path, "cleanTimeDirectories", shell_cmd)
        return

    removed = 0
    for entry in case_path.iterdir():
        if not entry.is_dir():
            continue
        try:
            value = float(entry.name)
        except ValueError:
            continue
        if value < 0:
            continue
        try:
            for child in entry.rglob("*"):
                if child.is_file():
                    child.unlink()
            entry.rmdir()
            removed += 1
        except OSError:
            continue
    if not silent:
        _show_message(stdscr, f"Removed {removed} time directories.")


def clean_case(stdscr: Any, case_path: Path) -> None:
    """
    Run CleanFunctions cleanCase to remove logs, time directories, etc.
    """
    wm_dir = _require_wm_project_dir(stdscr)
    if wm_dir and get_config().use_cleanfunctions:
        shell_cmd = f'. "{wm_dir}/bin/tools/CleanFunctions"; cleanCase'
        _run_shell_tool(stdscr, case_path, "cleanCase", shell_cmd)
        return

    remove_all_logs(stdscr, case_path)
    clean_time_directories(stdscr, case_path)


def safe_stop_screen(stdscr: Any, case_path: Path) -> None:
    stop_file = case_path / "stop"
    try:
        stop_file.write_text("")
    except OSError as exc:
        _show_message(stdscr, f"Failed to create stop file: {exc}")
        return
    _show_message(stdscr, "Created stop file. Solver will stop after next write.")


def solver_resurrection_screen(stdscr: Any, case_path: Path) -> None:
    control_dict = case_path / "system" / "controlDict"
    if not control_dict.is_file():
        _show_message(stdscr, "system/controlDict not found.")
        return
    latest = latest_time(case_path)
    if latest in ("0", "0.0", ""):
        _show_message(stdscr, "No latest time found to resume from.")
        return
    if set_start_from_latest(control_dict, latest):
        _show_message(stdscr, f"Set startFrom latestTime and startTime {latest}.")
        return
    _show_message(stdscr, "Failed to update controlDict (check OpenFOAM env).")


def _clean_clone(case_path: Path) -> None:  # noqa: C901
    for path in case_path.glob("log.*"):
        try:
            path.unlink()
        except OSError:
            continue
    for entry in case_path.iterdir():
        if entry.is_dir() and entry.name.startswith("processor"):
            shutil.rmtree(entry, ignore_errors=True)
    for entry in case_path.iterdir():
        if not entry.is_dir():
            continue
        try:
            value = float(entry.name)
        except ValueError:
            continue
        if value >= 0:
            shutil.rmtree(entry, ignore_errors=True)
    post = case_path / "postProcessing"
    if post.exists():
        shutil.rmtree(post, ignore_errors=True)
    mesh = case_path / "constant" / "polyMesh"
    if mesh.exists():
        shutil.rmtree(mesh, ignore_errors=True)


def clone_case(stdscr: Any, case_path: Path, name: str | None = None) -> None:
    if not name:
        stdscr.clear()
        name = prompt_input(stdscr, "New case name (folder): ")
        if name is None:
            return
        name = name.strip()
    if not name:
        return
    dest = Path(name)
    if not dest.is_absolute():
        dest = case_path.parent / dest
    if dest.exists():
        _show_message(stdscr, f"Destination already exists: {dest}")
        return
    try:
        shutil.copytree(case_path, dest, symlinks=True)
    except OSError as exc:
        _show_message(stdscr, f"Failed to clone case: {exc}")
        return
    _clean_clone(dest)
    _show_message(stdscr, f"Cloned case to {dest}")


def _decomposed_processors(case_path: Path) -> list[Path]:
    return sorted(p for p in case_path.iterdir() if p.is_dir() and p.name.startswith("processor"))


def reconstruct_manager_screen(stdscr: Any, case_path: Path) -> None:
    processors = _decomposed_processors(case_path)
    if not processors:
        _show_message(stdscr, "Case is not decomposed (no processor* directories).")
        return
    options = ["reconstructPar", "reconstructPar -latestTime", "Back"]
    menu = Menu(stdscr, "Reconstruct manager", options)
    choice = menu.navigate()
    if choice == -1 or choice == len(options) - 1:
        return
    if choice == 0:
        _run_simple_tool(stdscr, case_path, "reconstructPar", ["reconstructPar"])
    elif choice == 1:
        _run_simple_tool(
            stdscr, case_path, "reconstructPar -latestTime", ["reconstructPar", "-latestTime"],
        )


def reconstruct_latest_once(case_path: Path) -> tuple[bool, str]:
    processors = _decomposed_processors(case_path)
    if not processors:
        return False, "No processor directories found (skip reconstruct)."
    try:
        result = run_trusted(
            ["reconstructPar", "-latestTime"],
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return False, f"reconstructPar failed: {exc}"
    _write_tool_log(case_path, "reconstructPar", result.stdout, result.stderr)
    if result.returncode != 0:
        return False, f"reconstructPar exit code {result.returncode}"
    return True, "reconstructPar -latestTime completed."



def time_directory_pruner_screen(stdscr: Any, case_path: Path) -> None:  # noqa: C901
    times = time_directories(case_path)
    if len(times) < 2:
        _show_message(stdscr, "No time directories found to prune.")
        return

    stdscr.clear()
    raw = prompt_input(stdscr, "Keep every Nth time directory (e.g. 10): ")
    if raw is None:
        return
    raw = raw.strip()
    if not raw:
        return
    try:
        interval = int(raw)
    except ValueError:
        _show_message(stdscr, f"Invalid number: {raw}")
        return
    if interval <= 1:
        _show_message(stdscr, "Interval must be >= 2 to prune.")
        return

    keep: set[Path] = set()
    for idx, path in enumerate(times):
        if idx % interval == 0:
            keep.add(path)
    keep.add(times[-1])

    removed = 0
    for path in times:
        if path in keep:
            continue
        try:
            for child in path.rglob("*"):
                if child.is_file():
                    child.unlink()
            path.rmdir()
            removed += 1
        except OSError:
            continue

    _show_message(stdscr, f"Removed {removed} time directories.")


def yplus_screen(stdscr: Any, case_path: Path) -> None:
    """
    Run yPlus and show min/max/avg summary with optional raw output.
    """
    status_message(stdscr, "Running yPlus...")
    stdout, stderr = _run_tool_capture(case_path, "yPlus")
    _write_tool_log(case_path, "yPlus", stdout, stderr)
    stats = _parse_yplus_stats("\n".join([stdout, stderr]))
    if not stats:
        _show_message(stdscr, "No yPlus stats found in output.")
        return
    summary = _ascii_kv_table(
        "yPlus summary",
        [
            ("min", f"{stats.get('min', 'n/a')}"),
            ("max", f"{stats.get('max', 'n/a')}"),
            ("avg", f"{stats.get('avg', 'n/a')}"),
        ],
    )
    stdscr.clear()
    stdscr.addstr(summary + "\n")
    back_hint = key_hint("back", "h")
    stdscr.addstr(f"Press r for raw output, {back_hint} to return.\n")
    stdscr.refresh()
    ch = stdscr.getch()
    if ch in (ord("r"), ord("R")):
        Viewer(
            stdscr,
            "\n".join(["yPlus raw output", "", format_log_blob(stdout, stderr)]),
        ).display()


def _run_tool_capture(case_path: Path, name: str) -> tuple[str, str]:
    wm_dir = os.environ.get("WM_PROJECT_DIR")
    if wm_dir and get_config().use_runfunctions:
        shell_cmd = f'. "{wm_dir}/bin/tools/RunFunctions"; {name}'
        return _run_shell_capture(case_path, shell_cmd)

    bashrc = resolve_openfoam_bashrc()
    if bashrc:
        return _run_shell_capture(case_path, name)

    try:
        result = run_trusted(
            [name],
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return ("", f"Failed to run {name}: {exc}")
    return result.stdout, result.stderr


def _run_shell_capture(case_path: Path, shell_cmd: str) -> tuple[str, str]:
    command = with_bashrc(_expand_shell_command(shell_cmd, case_path))
    env = os.environ.copy()
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)
    try:
        result = run_trusted(
            ["bash", "--noprofile", "--norc", "-c", command],
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
    except OSError as exc:
        return ("", f"Failed to run command: {exc}")
    return result.stdout, result.stderr


def _parse_yplus_stats(text: str) -> dict[str, str]:
    stats: dict[str, str] = {}
    for line in text.splitlines():
        lower = line.lower()
        if "y+" not in lower and "yplus" not in lower:
            continue
        if "min" in lower and "min" not in stats:
            value = _float_after("min", line) or _first_float(line)
            if value is not None:
                stats["min"] = value
        if "max" in lower and "max" not in stats:
            value = _float_after("max", line) or _first_float(line)
            if value is not None:
                stats["max"] = value
        if ("avg" in lower or "average" in lower) and "avg" not in stats:
            value = _float_after("avg", line) or _float_after("average", line) or _first_float(line)
            if value is not None:
                stats["avg"] = value
    return stats


def _first_float(line: str) -> str | None:
    match = re.search(r"([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)", line)
    if match:
        return match.group(1)
    return None


def _float_after(label: str, line: str) -> str | None:
    pattern = rf"{label}\s*[:=]?\s*([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)"
    match = re.search(pattern, line, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def tool_dicts_screen(stdscr: Any, case_path: Path) -> None:
    items = [
        ("postProcess", case_path / "system" / "postProcessDict", ["postProcess", "-list"]),
        ("foamCalc", case_path / "system" / "foamCalcDict", ["foamCalc", "-help"]),
        ("topoSet", case_path / "system" / "topoSetDict", ["topoSetDict"]),
        ("setFields", case_path / "system" / "setFieldsDict", None),
    ]
    labels = [f"{name}: {path.relative_to(case_path)}" for name, path, _ in items]
    menu = Menu(stdscr, "Tool dictionaries", [*labels, "Back"])
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return

    name, path, helper_cmd = items[choice]
    if not _ensure_tool_dict(stdscr, case_path, name, path, helper_cmd):
        return
    _open_dict_preview(stdscr, path)


def _ensure_tool_dict(
    stdscr: Any,
    case_path: Path,
    name: str,
    path: Path,
    helper_cmd: list[str] | None,
) -> bool:
    if path.is_file():
        return True

    stdscr.clear()
    stdscr.addstr(f"{path.relative_to(case_path)} is missing.\n")
    stdscr.addstr("Provide a dictionary to continue.\n")
    stdscr.addstr("Generate template now? (y/N): ")
    stdscr.refresh()
    ch = stdscr.getch()
    if ch not in (ord("y"), ord("Y")):
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    generated = _generate_tool_dict_with_helper(case_path, helper_cmd, path)
    if not generated:
        _write_stub_dict(path, name)
    return True


def _generate_tool_dict_with_helper(
    case_path: Path, helper_cmd: list[str] | None, path: Path,
) -> bool:
    if not helper_cmd:
        return False
    try:
        result = run_trusted(
            helper_cmd,
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    output = (result.stdout or "").strip()
    if result.returncode == 0 and output and "FoamFile" in output:
        try:
            path.write_text(output + "\n")
        except OSError:
            return False
        return True
    return False


def _write_stub_dict(path: Path, tool_name: str) -> None:
    template = [
        "/*--------------------------------*- C++ -*----------------------------------*\\",
        f"| OpenFOAM {tool_name} dictionary (stub)                           |",
        "\\*---------------------------------------------------------------------------*/",
        "FoamFile",
        "{",
        "    version     2.0;",
        "    format      ascii;",
        "    class       dictionary;",
        f"    object      {path.name};",
        "}",
        "",
        "// TODO: fill in tool configuration.",
        "",
    ]
    path.write_text("\n".join(template))


def _open_dict_preview(stdscr: Any, path: Path) -> None:
    try:
        content = path.read_text()
    except OSError as exc:
        _show_message(stdscr, f"Failed to read {path.name}: {exc}")
        return
    viewer = Viewer(stdscr, content)
    viewer.display()


def _prompt_line(stdscr: Any, prompt: str) -> str:
    stdscr.clear()
    value = prompt_input(stdscr, prompt)
    if value is None:
        return ""
    return value.strip()


def foamlib_parametric_study_screen(  # noqa: C901, PLR0912
    stdscr: Any,
    case_path: Path,
) -> None:
    if not foamlib_available():
        _show_message(stdscr, "foamlib is not available.")
        return

    presets_path = case_path / "ofti.parametric"
    preset: ParametricPreset | None = None
    if presets_path.is_file():
        presets, errors = _read_parametric_presets(presets_path)
        if errors:
            _show_message(stdscr, "Errors in ofti.parametric; falling back to manual input.")
        elif presets:
            labels = [preset_item.name for preset_item in presets]
            menu = Menu(stdscr, "Parametric wizard", [*labels, "Manual entry", "Back"])
            choice = menu.navigate()
            if choice == -1 or choice == len(labels) + 1:
                return
            if choice < len(labels):
                preset = presets[choice]

    if preset is not None:
        dict_input = preset.dict_path
        entry = preset.entry
        values = preset.values
    else:
        dict_input = _prompt_line(
            stdscr,
            "Dictionary path (default system/controlDict): ",
        )
        if not dict_input:
            dict_input = "system/controlDict"
        entry = _prompt_line(stdscr, "Entry key (e.g. application): ")
        if not entry:
            _show_message(stdscr, "Entry key is required.")
            return
        values_line = _prompt_line(stdscr, "Values (comma-separated): ")
        values = [val.strip() for val in values_line.split(",") if val.strip()]
        if not values:
            _show_message(stdscr, "No values provided.")
            return
    run_line = _prompt_line(stdscr, "Run solver for each case? [y/N]: ")
    run_solver = run_line.strip().lower().startswith("y")

    try:
        created = build_parametric_cases(
            case_path,
            Path(dict_input),
            entry,
            values,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _show_message(stdscr, f"Parametric setup failed: {exc}")
        return

    failures: list[Path] = []
    if run_solver:
        failures = run_cases(created, check=False)

    lines = [
        f"Created {len(created)} case(s):",
        *[f"- {path}" for path in created],
    ]
    if run_solver:
        if failures:
            lines += ["", "Failures:", *[f"- {path}" for path in failures]]
        else:
            lines += ["", "All cases completed."]
    Viewer(stdscr, "\n".join(lines)).display()


def diagnostics_screen(stdscr: Any, case_path: Path) -> None:
    """
    System and case diagnostics based on common OpenFOAM tools.
    """
    tools = [
        ("foamSystemCheck", ["foamSystemCheck"]),
        ("foamInstallationTest", ["foamInstallationTest"]),
    ]
    labels = ["Case report", "Dictionary compare"] + [name for name, _ in tools] + [
        "Parallel consistency check",
    ]
    disabled = None
    if _no_foam_active():
        disabled = set(range(1, len(labels)))
    status_line = (
        "Limited mode: OpenFOAM env not found (simple editor only)"
        if _no_foam_active()
        else None
    )
    menu = Menu(
        stdscr,
        "Diagnostics",
        [*labels, "Back"],
        status_line=status_line,
        disabled_indices=disabled,
        help_lines=diagnostics_help(),
    )
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return

    if choice == 0:
        case_report_screen(stdscr, case_path)
        return
    if choice == 1:
        dictionary_compare_screen(stdscr, case_path)
        return
    if choice == len(tools) + 2:
        parallel_consistency_screen(stdscr, case_path)
        return

    name, cmd = tools[choice - 2]
    status_message(stdscr, f"Running {name}...")
    try:
        result = run_trusted(
            cmd,
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run {name}: {exc}"))
        return

    _write_tool_log(case_path, name, result.stdout, result.stderr)

    if name == "checkMesh":
        _show_checkmesh_summary(stdscr, result.stdout, result.stderr)
        return

    summary = format_command_result(
        [f"$ cd {case_path}", f"$ {' '.join(cmd)}"],
        CommandResult(result.returncode, result.stdout, result.stderr),
    )
    viewer = Viewer(stdscr, summary)
    viewer.display()


def case_report_screen(stdscr: Any, case_path: Path) -> None:
    solver = detect_solver(case_path)
    parallel = detect_parallel_settings(case_path)
    latest = latest_time(case_path)
    mesh = detect_mesh_stats(case_path)
    cells, faces, points = mesh_counts(case_path)
    log_files = list(case_path.glob("log.*"))
    size = _directory_size(case_path)
    lines = [
        "CASE REPORT",
        "",
        f"Path: {case_path}",
        f"Solver: {solver}",
        f"Latest time: {latest}",
        f"Parallel: {parallel}",
        f"Mesh: {mesh}",
    ]
    if any(val is not None for val in (cells, faces, points)):
        parts = []
        if cells is not None:
            parts.append(f"cells={cells}")
        if faces is not None:
            parts.append(f"faces={faces}")
        if points is not None:
            parts.append(f"points={points}")
        lines.append(f"Mesh counts: {', '.join(parts)}")
    lines += [
        f"Log files: {len(log_files)}",
        f"Disk usage: {_human_size(size)}",
    ]
    Viewer(stdscr, "\n".join(lines)).display()


def dictionary_compare_screen(stdscr: Any, case_path: Path) -> None:
    other_input = _prompt_line(
        stdscr,
        "Compare to case path (absolute or relative): ",
    )
    if not other_input:
        _show_message(stdscr, "No comparison path provided.")
        return
    other_path = Path(other_input).expanduser()
    if not other_path.is_dir():
        _show_message(stdscr, f"Not a directory: {other_path}")
        return
    diffs = compare_case_dicts(case_path, other_path)
    if not diffs:
        Viewer(stdscr, "No dictionary key differences detected.").display()
        return
    lines = [
        "DICTIONARY COMPARE",
        "",
        f"Current: {case_path}",
        f"Other:   {other_path}",
        "",
    ]
    for diff in diffs:
        lines.append(diff.rel_path)
        if diff.error:
            lines.append(f"  error: {diff.error}")
            lines.append("")
            continue
        if diff.missing_in_left:
            lines.append(f"  missing in current: {', '.join(diff.missing_in_left)}")
        if diff.missing_in_right:
            lines.append(f"  missing in other: {', '.join(diff.missing_in_right)}")
        lines.append("")
    Viewer(stdscr, "\n".join(lines)).display()


def _directory_size(path: Path) -> int:
    total = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


def _human_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} {units[-1]}"


def run_checkmesh(stdscr: Any, case_path: Path) -> None:
    status_message(stdscr, "Running checkMesh...")
    cmd = ["checkMesh"]
    try:
        result = run_trusted(
            cmd,
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run checkMesh: {exc}"))
        return
    _write_tool_log(case_path, "checkMesh", result.stdout, result.stderr)
    _record_tool_status("checkMesh", f"exit {result.returncode}")
    _show_checkmesh_summary(stdscr, result.stdout, result.stderr)


def run_blockmesh(stdscr: Any, case_path: Path) -> None:
    status_message(stdscr, "Running blockMesh...")
    cmd = ["blockMesh"]
    try:
        result = run_trusted(
            cmd,
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run blockMesh: {exc}"))
        return
    _write_tool_log(case_path, "blockMesh", result.stdout, result.stderr)
    _record_tool_status("blockMesh", f"exit {result.returncode}")
    summary = format_command_result(
        [f"$ cd {case_path}", "$ blockMesh"],
        CommandResult(result.returncode, result.stdout, result.stderr),
    )
    Viewer(stdscr, summary).display()


def run_decomposepar(stdscr: Any, case_path: Path) -> None:
    decompose_dict = case_path / "system" / "decomposeParDict"
    if not decompose_dict.is_file():
        rel_path = Path("system") / "decomposeParDict"
        stdscr.clear()
        stdscr.addstr("Missing system/decomposeParDict.\n\n")
        stdscr.addstr("Press c to create from examples, or any other key to return.\n")
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (ord("c"), ord("C")):
            created = write_example_template(decompose_dict, rel_path)
            if created:
                _show_message(stdscr, "Created decomposeParDict from examples.")
            else:
                _show_message(stdscr, "No example template found for decomposeParDict.")
        return
    status_message(stdscr, "Running decomposePar...")
    cmd = ["decomposePar"]
    try:
        result = run_trusted(
            cmd,
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run decomposePar: {exc}"))
        return
    _write_tool_log(case_path, "decomposePar", result.stdout, result.stderr)
    _record_tool_status("decomposePar", f"exit {result.returncode}")
    summary = format_command_result(
        [f"$ cd {case_path}", "$ decomposePar"],
        CommandResult(result.returncode, result.stdout, result.stderr),
    )
    Viewer(stdscr, summary).display()


def _show_checkmesh_summary(stdscr: Any, stdout: str, stderr: str) -> None:
    output = "\n".join([stdout or "", stderr or ""]).strip()
    summary = format_checkmesh_summary(output)
    stdscr.clear()
    stdscr.addstr(summary + "\n")
    back_hint = key_hint("back", "h")
    stdscr.addstr(f"Press r for raw output, {back_hint} to return.\n")
    stdscr.refresh()
    ch = stdscr.getch()
    if ch in (ord("r"), ord("R")):
        Viewer(
            stdscr,
            "\n".join(["checkMesh raw output", "", format_log_blob(stdout, stderr)]),
        ).display()


def _parallel_consistency_report(case_path: Path) -> tuple[str, list[str]]:
    decompose_dict = case_path / "system" / "decomposeParDict"
    if not decompose_dict.is_file():
        return ("missing", ["system/decomposeParDict not found."])

    expected = read_number_of_subdomains(decompose_dict)

    processors = _decomposed_processors(case_path)
    actual = len(processors)

    lines = []
    if expected is None:
        lines.append("numberOfSubdomains not set or invalid.")
    else:
        lines.append(f"numberOfSubdomains: {expected}")
    lines.append(f"processor* directories: {actual}")

    if expected is None:
        status = "warn"
    elif expected != actual:
        status = "mismatch"
    else:
        status = "ok"
    return (status, lines)


def parallel_consistency_screen(stdscr: Any, case_path: Path) -> None:
    status, lines = _parallel_consistency_report(case_path)
    header = "Parallel consistency check"
    if status == "missing":
        message = [header, "", *lines, "", "No decomposeParDict found."]
    elif status == "mismatch":
        message = [header, "", *lines, "", "Mismatch: re-run decomposePar or update dict."]
    elif status == "warn":
        message = [header, "", *lines, "", "Add numberOfSubdomains to decomposeParDict."]
    else:
        message = [header, "", *lines, "", "OK: counts match."]
    Viewer(stdscr, "\n".join(message)).display()


def log_tail_screen(stdscr: Any, case_path: Path) -> None:  # noqa: C901, PLR0912
    log_files = sorted(case_path.glob("log.*"))
    if not log_files:
        _show_message(stdscr, "No log.* files found in case directory.")
        return

    labels = [p.name for p in log_files]
    menu = Menu(stdscr, "Select log to tail", [*labels, "Back"])
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




def _ascii_kv_table(title: str, rows: list[tuple[str, str]]) -> str:
    if not rows:
        return title
    left_width = max(len(label) for label, _value in rows)
    right_width = max(len(value) for _label, value in rows)
    header_width = max(len(title), left_width + right_width + 3)
    left_width = max(left_width, header_width - right_width - 3)

    top = "+" + "-" * (left_width + 2) + "+" + "-" * (right_width + 2) + "+"
    lines = [top]
    lines.append(
        f"| {title.ljust(left_width + right_width + 1)} |".ljust(
            left_width + right_width + 5,
        ),
    )
    lines.append(top)
    for label, value in rows:
        lines.append(f"| {label.ljust(left_width)} | {value.ljust(right_width)} |")
    lines.append(top)
    return "\\n".join(lines)

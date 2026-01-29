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
from typing import Any

from ofti.core.case import read_number_of_subdomains, set_start_from_latest
from ofti.core.checkmesh import extract_last_courant, format_checkmesh_summary
from ofti.core.entry_io import read_entry as read_entry
from ofti.core.times import latest_time, time_directories
from ofti.core.tool_output import CommandResult, format_command_result, format_log_blob
from ofti.foam.config import get_config, key_hint, key_in
from ofti.foam.exceptions import QuitAppError
from ofti.foam.openfoam import OpenFOAMError
from ofti.foam.subprocess_utils import resolve_executable, run_trusted
from ofti.foamlib_adapter import available as foamlib_available
from ofti.foamlib_logs import parse_residuals
from ofti.foamlib_parametric import build_parametric_cases
from ofti.foamlib_runner import run_cases
from ofti.tools.helpers import (
    auto_detect_bashrc_paths,
    resolve_openfoam_bashrc,
    with_bashrc,
    wm_project_dir_from_bashrc,
)
from ofti.ui_curses.help import diagnostics_help, tools_help
from ofti.ui_curses.layout import status_message
from ofti.ui_curses.menus import Menu
from ofti.ui_curses.viewer import Viewer


@dataclass
class LastToolRun:
    name: str
    kind: str
    command: list[str] | str


_LAST_TOOL_RUN: LastToolRun | None = None


def _no_foam_active() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return os.environ.get("OFTI_NO_FOAM") == "1"


def _no_foam_hint() -> str:
    if _no_foam_active():
        return " (no-foam mode may prevent OpenFOAM tools from running)"
    return ""


def _with_no_foam_hint(message: str) -> str:
    hint = _no_foam_hint()
    return f"{message}{hint}" if hint else message


def _record_last_tool(name: str, kind: str, command: list[str] | str) -> None:
    global _LAST_TOOL_RUN  # noqa: PLW0603
    _LAST_TOOL_RUN = LastToolRun(name=name, kind=kind, command=command)




def tool_status_mode() -> str:
    mode = "no-foam" if os.environ.get("OFTI_NO_FOAM") == "1" else "foam"
    wm_dir = os.environ.get("WM_PROJECT_DIR")
    suffix = f" ({wm_dir})" if wm_dir else ""
    return f"mode: {mode}{suffix}"


def _job_dir_hint() -> str | None:
    job_dir = os.environ.get("FOAM_JOB_DIR", "~/.OpenFOAM/jobControl")
    path = Path(job_dir).expanduser()
    if path.is_dir():
        return None
    return f"hint: FOAM_JOB_DIR missing at {path}. Create it with: mkdir -p {path}"


def _maybe_job_hint(name: str) -> str | None:
    if name in ("foamPrintJobs", "foamCheckJobs", "foamJob", "foamEndJob"):
        return _job_dir_hint()
    return None


def _load_presets_from_path(cfg_path: Path) -> list[tuple[str, list[str]]]:
    """
    Load tool presets from a colon-delimited config file.
    """
    presets: list[tuple[str, list[str]]] = []
    if not cfg_path.is_file():
        return presets

    try:
        for raw_line in cfg_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            name, cmd_str = line.split(":", 1)
            name = name.strip()
            cmd_str = cmd_str.strip()
            if not name or not cmd_str:
                continue
            try:
                cmd = shlex.split(cmd_str)
            except ValueError:
                continue
            presets.append((name, cmd))
    except OSError:
        return presets

    return presets


def _normalize_tool_name(name: str) -> str:
    lowered = name.strip().lower()
    return "".join(ch for ch in lowered if ch.isalnum() or ch in ("-", "_", ".", ":"))


def list_tool_commands(case_path: Path) -> list[str]:
    return sorted(set(_tool_alias_keys(case_path)))


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
        ("snappyHexMesh", ["snappyHexMesh"]),
        ("decomposePar", ["decomposePar"]),
        ("reconstructPar", ["reconstructPar"]),
        ("foamListTimes", ["foamListTimes"]),
    ]
    extra_tools = load_tool_presets(case_path)
    job_tools = [
        ("foamCheckJobs", ["foamCheckJobs"]),
        ("foamPrintJobs", ["foamPrintJobs"]),
    ]
    post_tools = load_postprocessing_presets(case_path)

    for name, cmd in base_tools + extra_tools + job_tools:
        add(name, run_simple(name, cmd))

    for name, cmd in post_tools:
        add(name, run_simple(name, cmd))
        add(f"post.{name}", run_simple(name, cmd))
        add(f"post:{name}", run_simple(name, cmd))

    add("rerun", lambda: rerun_last_tool(stdscr, case_path))
    add("last", lambda: rerun_last_tool(stdscr, case_path))
    add("foamjob", lambda: foam_job_prompt(stdscr, case_path))
    add("foamendjob", lambda: foam_end_job_prompt(stdscr, case_path))
    add("jobstatus", lambda: job_status_poll_screen(stdscr, case_path))
    add("job_status", lambda: job_status_poll_screen(stdscr, case_path))
    add("runscript", lambda: run_shell_script_screen(stdscr, case_path))
    add("foamdictionary", lambda: foam_dictionary_prompt(stdscr, case_path))
    add("postprocess", lambda: post_process_prompt(stdscr, case_path))
    add("foamcalc", lambda: foam_calc_prompt(stdscr, case_path))
    add("toposet", lambda: topo_set_prompt(stdscr, case_path))
    add("tool_dicts", lambda: tool_dicts_screen(stdscr, case_path))
    add("tooldicts", lambda: tool_dicts_screen(stdscr, case_path))
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
    add("logtail", lambda: log_tail_screen(stdscr, case_path))
    add("logs", lambda: logs_screen(stdscr, case_path))
    add("viewlogs", lambda: logs_screen(stdscr, case_path))
    add("residuals", lambda: residual_timeline_screen(stdscr, case_path))
    add("residual_timeline", lambda: residual_timeline_screen(stdscr, case_path))
    add("probes", lambda: probes_viewer_screen(stdscr, case_path))
    add("probesviewer", lambda: probes_viewer_screen(stdscr, case_path))

    return aliases


def _tool_alias_keys(case_path: Path) -> list[str]:
    keys: list[str] = []

    base_tools = [
        ("blockMesh", ["blockMesh"]),
        ("snappyHexMesh", ["snappyHexMesh"]),
        ("decomposePar", ["decomposePar"]),
        ("reconstructPar", ["reconstructPar"]),
        ("foamListTimes", ["foamListTimes"]),
    ]
    extra_tools = load_tool_presets(case_path)
    job_tools = [
        ("foamCheckJobs", ["foamCheckJobs"]),
        ("foamPrintJobs", ["foamPrintJobs"]),
    ]
    post_tools = load_postprocessing_presets(case_path)

    for name, _ in base_tools + extra_tools + job_tools:
        keys.append(_normalize_tool_name(name))

    for name, _ in post_tools:
        keys.append(_normalize_tool_name(name))
        keys.append(_normalize_tool_name(f"post.{name}"))
        keys.append(_normalize_tool_name(f"post:{name}"))

    keys += [
        _normalize_tool_name("checkmesh"),
        _normalize_tool_name("logtail"),
        _normalize_tool_name("logs"),
        _normalize_tool_name("viewlogs"),
        _normalize_tool_name("residuals"),
        _normalize_tool_name("residual_timeline"),
        _normalize_tool_name("probes"),
        _normalize_tool_name("probesviewer"),
    ]

    keys.extend(
        [
            _normalize_tool_name("rerun"),
            _normalize_tool_name("last"),
            _normalize_tool_name("foamJob"),
            _normalize_tool_name("foamEndJob"),
            _normalize_tool_name("runScript"),
            _normalize_tool_name("foamDictionary"),
            _normalize_tool_name("postProcess"),
            _normalize_tool_name("foamCalc"),
            _normalize_tool_name("topoSet"),
            _normalize_tool_name("tool_dicts"),
            _normalize_tool_name("toolDicts"),
            _normalize_tool_name("runCurrentSolver"),
            _normalize_tool_name("runLive"),
            _normalize_tool_name("removeLogs"),
            _normalize_tool_name("cleanTimeDirs"),
            _normalize_tool_name("cleanCase"),
            _normalize_tool_name("reconstructManager"),
            _normalize_tool_name("timeDirPruner"),
            _normalize_tool_name("safeStop"),
            _normalize_tool_name("solveResume"),
            _normalize_tool_name("clone"),
            _normalize_tool_name("yPlus"),
        ],
    )

    return keys


def _show_message(stdscr: Any, message: str) -> None:
    stdscr.clear()
    stdscr.addstr(message + "\n")
    stdscr.addstr("Press any key to continue.\n")
    stdscr.refresh()
    key = stdscr.getch()
    if key_in(key, get_config().keys.get("quit", [])):
        raise QuitAppError()


def load_tool_presets(case_path: Path) -> list[tuple[str, list[str]]]:
    """
    Load extra tools from an optional per-case file `ofti.tools`.

    Format (one per line, lines starting with # are ignored):
      name: command with args
    Example:
      simpleFoam: simpleFoam -case .
    """
    cfg_path = case_path / "ofti.tools"
    return _load_presets_from_path(cfg_path)


def load_postprocessing_presets(case_path: Path) -> list[tuple[str, list[str]]]:
    """
    Load optional post-processing commands from `ofti.postprocessing`.
    Same format as `ofti.tools`.
    """
    cfg_path = case_path / "ofti.postprocessing"
    return _load_presets_from_path(cfg_path)


def _run_simple_tool(stdscr: Any, case_path: Path, name: str, cmd: list[str]) -> None:
    status_message(stdscr, f"Running {name}...")
    expanded = _expand_command(cmd, case_path)
    wm_dir = os.environ.get("WM_PROJECT_DIR")
    if wm_dir and get_config().use_runfunctions:
        cmd_str = " ".join(shlex.quote(part) for part in expanded)
        shell_cmd = f'. "{wm_dir}/bin/tools/RunFunctions"; runApplication {cmd_str}'
        _record_last_tool(name, "shell", shell_cmd)
        _run_shell_tool(stdscr, case_path, name, shell_cmd)
        return

    bashrc = resolve_openfoam_bashrc()
    if bashrc:
        cmd_str = " ".join(shlex.quote(part) for part in expanded)
        shell_cmd = f"{cmd_str}"
        _record_last_tool(name, "shell", shell_cmd)
        _run_shell_tool(stdscr, case_path, name, shell_cmd)
        return

    _record_last_tool(name, "simple", expanded)
    try:
        result = run_trusted(
            expanded,
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run {name}: {exc}"))
        return

    hint = _maybe_job_hint(name)
    summary = format_command_result(
        [f"$ cd {case_path}", f"$ {' '.join(cmd)}"],
        CommandResult(result.returncode, result.stdout, result.stderr),
        hint=hint,
    )
    viewer = Viewer(stdscr, summary)
    viewer.display()


def _run_shell_tool(stdscr: Any, case_path: Path, name: str, shell_cmd: str) -> None:
    status_message(stdscr, f"Running {name}...")
    shell_cmd = with_bashrc(_expand_shell_command(shell_cmd, case_path))
    _record_last_tool(name, "shell", shell_cmd)
    env = os.environ.copy()
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)
    try:
        result = run_trusted(
            ["bash", "--noprofile", "--norc", "-c", shell_cmd],
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
    except OSError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run {name}: {exc}"))
        return

    hint = _maybe_job_hint(name)
    summary = format_command_result(
        [f"$ cd {case_path}", f"$ bash --noprofile --norc -c {shell_cmd}"],
        CommandResult(result.returncode, result.stdout, result.stderr),
        hint=hint,
    )
    viewer = Viewer(stdscr, summary)
    viewer.display()


def tools_screen(stdscr: Any, case_path: Path) -> None:  # noqa: C901
    """
    Tools menu with common solvers/utilities, job helpers, logs, and
    optional shell scripts, all in a single flat list.
    """
    base_tools = [
        ("foamListTimes", ["foamListTimes"]),
    ]
    extra_tools = load_tool_presets(case_path)
    job_tools = [
        ("foamCheckJobs", ["foamCheckJobs"]),
        ("foamPrintJobs", ["foamPrintJobs"]),
    ]
    post_tools = [
        (f"[post] {name}", cmd) for name, cmd in load_postprocessing_presets(case_path)
    ]

    simple_tools = base_tools + extra_tools + job_tools + post_tools

    labels = ["Re-run last tool"] + [name for name, _ in simple_tools] + [
        "Diagnostics",
        "Job status (poll)",
        "foamJob (run job)",
        "foamEndJob (stop job)",
        "Run .sh script",
        "foamDictionary (prompt)",
        "topoSet (prompt)",
        "Tool dicts (postProcess/topoSet/foamCalc)",
        "Clone case",
    ]

    def hint_for(idx: int) -> str:
        if idx == 0:
            if _LAST_TOOL_RUN is None:
                base = "Re-run last tool (none yet)"
            else:
                base = f"Re-run last tool: {_LAST_TOOL_RUN.name}"
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
            "Poll foamCheckJobs/foamPrintJobs output",
            "Run foamJob with custom args",
            "Stop job via foamEndJob",
            "Run a shell script from case folder",
            "Run foamDictionary interactively",
            "Run topoSet with args (uses topoSetDict)",
            "Create/open tool dictionaries",
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
        job_status_poll_screen(stdscr, case_path)
    elif special_index == 2:
        foam_job_prompt(stdscr, case_path)
    elif special_index == 3:
        foam_end_job_prompt(stdscr, case_path)
    elif special_index == 4:
        run_shell_script_screen(stdscr, case_path)
    elif special_index == 5:
        foam_dictionary_prompt(stdscr, case_path)
    elif special_index == 6:
        topo_set_prompt(stdscr, case_path)
    elif special_index == 7:
        tool_dicts_screen(stdscr, case_path)
    elif special_index == 8:
        clone_case(stdscr, case_path)


def logs_screen(stdscr: Any, case_path: Path) -> None:
    """
    Simple log viewer for files matching log.* in the case directory.
    """
    while True:
        log_files = sorted(case_path.glob("log.*"))
        if not log_files:
            _show_message(stdscr, "No log.* files found in case directory.")
            return

        labels = [p.name for p in log_files]
        menu = Menu(stdscr, "Select log file", [*labels, "Back"])
        choice = menu.navigate()
        if choice == -1 or choice == len(labels):
            return

        path = log_files[choice]
        try:
            text = path.read_text()
        except OSError as exc:
            _show_message(stdscr, f"Failed to read {path.name}: {exc}")
            continue

        viewer = Viewer(stdscr, text)
        viewer.display()


def residual_timeline_screen(stdscr: Any, case_path: Path) -> None:
    """
    Parse residuals from a selected log file and show a summary table + plot.
    """
    log_files = sorted(case_path.glob("log.*"))
    if not log_files:
        _show_message(stdscr, "No log.* files found in case directory.")
        return
    labels = [p.name for p in log_files]
    menu = Menu(stdscr, "Select log file for residuals", [*labels, "Back"])
    choice = menu.navigate()
    if choice == -1 or choice == len(labels):
        return
    path = log_files[choice]
    try:
        text = path.read_text()
    except OSError as exc:
        _show_message(stdscr, f"Failed to read {path.name}: {exc}")
        return

    residuals = parse_residuals(text)
    if not residuals:
        _show_message(stdscr, f"No residuals found in {path.name}.")
        return
    _height, width = stdscr.getmaxyx()
    plot_width = max(10, min(50, width - 28))
    lines = ["Residuals summary", ""]
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


def job_status_poll_screen(stdscr: Any, case_path: Path) -> None:
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
    if _LAST_TOOL_RUN is None:
        _show_message(stdscr, "No previous tool run recorded.")
        return

    last = _LAST_TOOL_RUN
    if last.kind == "shell":
        _run_shell_tool(stdscr, case_path, f"Re-run {last.name}", str(last.command))
    else:
        _run_simple_tool(stdscr, case_path, f"Re-run {last.name}", list(last.command))


def foam_dictionary_prompt(stdscr: Any, case_path: Path) -> None:
    """
    Prompt for a dictionary file and optional arguments to pass to foamDictionary.
    """
    curses.echo()
    stdscr.clear()
    stdscr.addstr("Relative path to dictionary (default system/controlDict): ")
    stdscr.refresh()
    path_input = stdscr.getstr().decode().strip()
    if not path_input:
        path_input = "system/controlDict"

    dictionary_path = (case_path / path_input).resolve()
    if not dictionary_path.is_file():
        curses.noecho()
        _show_message(stdscr, f"{dictionary_path} not found.")
        return

    stdscr.addstr("foamDictionary args (e.g. -entry application): ")
    stdscr.refresh()
    args_line = stdscr.getstr().decode().strip()
    curses.noecho()

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


def post_process_prompt(stdscr: Any, case_path: Path) -> None:
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
    curses.echo()
    stdscr.clear()
    stdscr.addstr("postProcess args (e.g. -latestTime -funcs '(mag(U))'):\n")
    stdscr.addstr(f"Tip: latest time detected = {latest}\n")
    stdscr.addstr("> ")
    stdscr.refresh()
    args_line = stdscr.getstr().decode().strip()
    curses.noecho()

    try:
        args = shlex.split(args_line) if args_line else ["-latestTime"]
    except ValueError as exc:
        _show_message(stdscr, f"Invalid arguments: {exc}")
        return

    cmd = ["postProcess", *args]
    _run_simple_tool(stdscr, case_path, "postProcess", cmd)


def foam_calc_prompt(stdscr: Any, case_path: Path) -> None:
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
    curses.echo()
    stdscr.clear()
    stdscr.addstr("foamCalc args (e.g. components U -latestTime):\n")
    stdscr.addstr(f"Tip: latest time detected = {latest}\n")
    stdscr.addstr("> ")
    stdscr.refresh()
    args_line = stdscr.getstr().decode().strip()
    curses.noecho()

    if not args_line:
        _show_message(stdscr, "No arguments provided for foamCalc.")
        return

    try:
        args = shlex.split(args_line)
    except ValueError as exc:
        _show_message(stdscr, f"Invalid arguments: {exc}")
        return

    cmd = ["foamCalc", *args]
    _run_simple_tool(stdscr, case_path, "foamCalc", cmd)


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
    curses.echo()
    stdscr.clear()
    stdscr.addstr("topoSet args (press Enter to run with defaults):\n")
    stdscr.addstr("> ")
    stdscr.refresh()
    args_line = stdscr.getstr().decode().strip()
    curses.noecho()

    try:
        args = shlex.split(args_line) if args_line else []
    except ValueError as exc:
        _show_message(stdscr, f"Invalid arguments: {exc}")
        return

    cmd = ["topoSet", *args]
    _run_simple_tool(stdscr, case_path, "topoSet", cmd)


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

    wm_dir = _require_wm_project_dir(stdscr)
    if wm_dir and get_config().use_runfunctions:
        shell_cmd = f'. "{wm_dir}/bin/tools/RunFunctions"; runApplication {shlex.quote(solver)}'
        _run_shell_tool(stdscr, case_path, f"runApplication {solver}", shell_cmd)
        return

    _run_simple_tool(stdscr, case_path, solver, [solver])


def run_current_solver_live(stdscr: Any, case_path: Path) -> None:
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


def remove_all_logs(stdscr: Any, case_path: Path) -> None:
    """
    Remove log.* files using CleanFunctions helpers.
    """
    wm_dir = _require_wm_project_dir(stdscr)
    if wm_dir and get_config().use_cleanfunctions:
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
    _show_message(stdscr, f"Removed {removed} log files.")


def clean_time_directories(stdscr: Any, case_path: Path) -> None:
    """
    Remove time directories using CleanFunctions.
    """
    wm_dir = _require_wm_project_dir(stdscr)
    if wm_dir and get_config().use_cleanfunctions:
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
        stdscr.addstr("New case name (folder): ")
        stdscr.refresh()
        try:
            name = stdscr.getstr().decode("utf-8").strip()
        except OSError:
            return
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



def time_directory_pruner_screen(stdscr: Any, case_path: Path) -> None:  # noqa: C901
    times = time_directories(case_path)
    if len(times) < 2:
        _show_message(stdscr, "No time directories found to prune.")
        return

    stdscr.clear()
    stdscr.addstr("Keep every Nth time directory (e.g. 10): ")
    stdscr.refresh()
    try:
        raw = stdscr.getstr().decode("utf-8").strip()
    except OSError:
        return
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


def _expand_command(cmd: list[str], case_path: Path) -> list[str]:
    latest = latest_time(case_path)
    return [part.replace("{{latestTime}}", latest) for part in cmd]


def _expand_shell_command(shell_cmd: str, case_path: Path) -> str:
    latest = latest_time(case_path)
    return shell_cmd.replace("{{latestTime}}", latest)



def tool_dicts_screen(stdscr: Any, case_path: Path) -> None:
    items = [
        ("postProcess", case_path / "system" / "postProcessDict", ["postProcess", "-list"]),
        ("foamCalc", case_path / "system" / "foamCalcDict", ["foamCalc", "-help"]),
        ("topoSet", case_path / "system" / "topoSetDict", ["topoSetDict"]),
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


def foam_job_prompt(stdscr: Any, case_path: Path) -> None:
    """
    Prompt for foamJob arguments and run it.
    """
    curses.echo()
    stdscr.clear()
    stdscr.addstr("foamJob arguments (e.g. simpleFoam -case .): ")
    stdscr.refresh()
    arg_line = stdscr.getstr().decode().strip()
    curses.noecho()

    if not arg_line:
        return

    try:
        args = shlex.split(arg_line)
    except ValueError as exc:
        _show_message(stdscr, f"Invalid arguments: {exc}")
        return

    try:
        result = run_trusted(
            ["foamJob", *args],
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run foamJob: {exc}"))
        return

    hint = _maybe_job_hint("foamJob")
    summary = format_command_result(
        [f"$ cd {case_path}", f"$ foamJob {' '.join(args)}"],
        CommandResult(result.returncode, result.stdout, result.stderr),
        hint=hint,
    )
    viewer = Viewer(stdscr, summary)
    viewer.display()


def foam_end_job_prompt(stdscr: Any, case_path: Path) -> None:
    """
    Prompt for foamEndJob arguments and run it.
    """
    curses.echo()
    stdscr.clear()
    stdscr.addstr("foamEndJob arguments (e.g. simpleFoam): ")
    stdscr.refresh()
    arg_line = stdscr.getstr().decode().strip()
    curses.noecho()

    if not arg_line:
        return

    try:
        args = shlex.split(arg_line)
    except ValueError as exc:
        _show_message(stdscr, f"Invalid arguments: {exc}")
        return

    try:
        result = run_trusted(
            ["foamEndJob", *args],
            cwd=case_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run foamEndJob: {exc}"))
        return

    hint = _maybe_job_hint("foamEndJob")
    summary = format_command_result(
        [f"$ cd {case_path}", f"$ foamEndJob {' '.join(args)}"],
        CommandResult(result.returncode, result.stdout, result.stderr),
        hint=hint,
    )
    viewer = Viewer(stdscr, summary)
    viewer.display()


def _prompt_line(stdscr: Any, prompt: str) -> str:
    curses.echo()
    stdscr.clear()
    stdscr.addstr(prompt)
    stdscr.refresh()
    value = stdscr.getstr().decode().strip()
    curses.noecho()
    return value


def foamlib_parametric_study_screen(stdscr: Any, case_path: Path) -> None:
    if not foamlib_available():
        _show_message(stdscr, "foamlib is not available.")
        return

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
    labels = [name for name, _ in tools] + [
        "Parallel consistency check",
    ]
    disabled = set(range(len(labels))) if _no_foam_active() else None
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

    if choice == len(tools):
        parallel_consistency_screen(stdscr, case_path)
        return

    name, cmd = tools[choice]
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
    Viewer(
        stdscr,
        "\n".join(["blockMesh output", "", format_log_blob(result.stdout, result.stderr)]),
    ).display()


def run_decomposepar(stdscr: Any, case_path: Path) -> None:
    decompose_dict = case_path / "system" / "decomposeParDict"
    if not decompose_dict.is_file():
        _show_message(stdscr, "Missing system/decomposeParDict.")
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
    Viewer(
        stdscr,
        "\n".join(["decomposePar output", "", format_log_blob(result.stdout, result.stderr)]),
    ).display()


def _write_tool_log(case_path: Path, name: str, stdout: str, stderr: str) -> None:
    if not stdout and not stderr:
        return
    log_path = case_path / f"log.{name}"
    content = "\n".join([f"tool: {name}", "", format_log_blob(stdout, stderr), ""])
    with suppress(OSError):
        log_path.write_text(content)


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

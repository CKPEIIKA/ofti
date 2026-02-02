from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ofti.core.case import detect_mesh_stats, detect_parallel_settings, detect_solver
from ofti.core.dict_compare import compare_case_dicts
from ofti.core.mesh_info import mesh_counts
from ofti.core.times import latest_time
from ofti.core.tool_output import CommandResult, format_command_result
from ofti.foam.subprocess_utils import run_trusted as _run_trusted
from ofti.tools import run as run_tools
from ofti.tools.input_prompts import prompt_line
from ofti.tools.menu_helpers import build_menu
from ofti.tools.runner import _no_foam_active, _show_message, _with_no_foam_hint, _write_tool_log
from ofti.ui_curses.help import diagnostics_help
from ofti.ui_curses.layout import status_message
from ofti.ui_curses.viewer import Viewer

run_trusted = _run_trusted


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


def diagnostics_screen(
    stdscr: Any,
    case_path: Path,
    *,
    command_handler: Callable[[str], str | None] | None = None,
    command_suggestions: Callable[[], list[str]] | None = None,
) -> None:
    """System and case diagnostics based on common OpenFOAM tools."""
    tools = [
        ("foamSystemCheck", ["foamSystemCheck"]),
        ("foamInstallationTest", ["foamInstallationTest"]),
    ]
    labels = [
        "Case report",
        "Dictionary compare",
    ] + [name for name, _ in tools] + ["Parallel consistency check"]
    disabled = None
    if _no_foam_active():
        disabled = set(range(1, len(labels)))
    status_line = (
        "Limited mode: OpenFOAM env not found (simple editor only)"
        if _no_foam_active()
        else None
    )
    menu = build_menu(
        stdscr,
        "Diagnostics",
        [*labels, "Back"],
        menu_key="menu:diagnostics",
        status_line=status_line,
        disabled_indices=disabled,
        command_handler=command_handler,
        command_suggestions=command_suggestions,
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
        run_tools.parallel_consistency_screen(stdscr, case_path)
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
        run_tools._show_checkmesh_summary(stdscr, result.stdout, result.stderr)
        return

    summary = format_command_result(
        [f"$ cd {case_path}", f"$ {' '.join(cmd)}"],
        CommandResult(result.returncode, result.stdout, result.stderr),
    )
    viewer = Viewer(stdscr, summary)
    viewer.display()


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


def _prompt_line(stdscr: Any, prompt: str) -> str:
    stdscr.clear()
    value = prompt_line(stdscr, prompt)
    if value is None:
        return ""
    return value.strip()

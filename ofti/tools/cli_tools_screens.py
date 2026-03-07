from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ofti.tools.cli_tools import knife as knife_ops
from ofti.tools.cli_tools import plot as plot_ops
from ofti.tools.cli_tools import run as run_ops
from ofti.tools.cli_tools import watch as watch_ops
from ofti.tools.input_prompts import prompt_line
from ofti.tools.menu_helpers import build_menu
from ofti.tools.runner import _show_message
from ofti.ui_curses.viewer import Viewer


def cli_tools_screen(
    stdscr: Any,
    case_path: Path,
    *,
    command_handler: Callable[[str], str | None] | None = None,
    command_suggestions: Callable[[], list[str]] | None = None,
) -> None:
    labels = [
        "Knife",
        "Plot",
        "Watch",
        "Run",
        "Back",
    ]
    while True:
        menu = build_menu(
            stdscr,
            "CLI tools",
            labels,
            menu_key="menu:cli_tools",
            command_handler=command_handler,
            command_suggestions=command_suggestions,
        )
        choice = menu.navigate()
        if choice in (-1, len(labels) - 1):
            return
        if choice == 0:
            _knife_screen(stdscr, case_path)
        elif choice == 1:
            _plot_screen(stdscr, case_path)
        elif choice == 2:
            _watch_screen(stdscr, case_path)
        elif choice == 3:
            _run_screen(stdscr, case_path)


def _knife_screen(stdscr: Any, case_path: Path) -> None:  # noqa: C901, PLR0911, PLR0912
    labels = [
        "Preflight",
        "Doctor",
        "Status",
        "Compare to another case",
        "Back",
    ]
    menu = build_menu(stdscr, "CLI tools: knife", labels, menu_key="menu:cli_tools_knife")
    choice = menu.navigate()
    if choice in (-1, len(labels) - 1):
        return
    if choice == 0:
        try:
            payload = knife_ops.preflight_payload(case_path)
        except ValueError as exc:
            _show_message(stdscr, str(exc))
            return
        lines = [f"case={payload['case']}"]
        for key, value in payload["checks"].items():
            lines.append(f"{key}={'ok' if value else 'missing'}")
        if payload["solver_error"]:
            lines.append(f"solver_error={payload['solver_error']}")
        lines.append(f"ok={payload['ok']}")
        Viewer(stdscr, "\n".join(lines)).display()
        return
    if choice == 1:
        try:
            payload = knife_ops.doctor_payload(case_path)
        except ValueError as exc:
            _show_message(stdscr, str(exc))
            return
        lines = list(payload["lines"])
        if payload["errors"]:
            lines += ["", "Errors:", *[f"- {item}" for item in payload["errors"]]]
        if payload["warnings"]:
            lines += ["", "Warnings:", *[f"- {item}" for item in payload["warnings"]]]
        if not payload["errors"] and not payload["warnings"]:
            lines += ["", "OK: no issues found."]
        Viewer(stdscr, "\n".join(lines)).display()
        return
    if choice == 2:
        try:
            payload = knife_ops.status_payload(case_path)
        except ValueError as exc:
            _show_message(stdscr, str(exc))
            return
        lines = [
            f"case={payload['case']}",
            f"latest_time={payload['latest_time']}",
        ]
        if payload["solver_error"]:
            lines.append(f"solver_error={payload['solver_error']}")
        else:
            lines.append(f"solver={payload['solver']}")
            lines.append(f"solver_status={payload['solver_status'] or 'not tracked'}")
        lines.append(f"jobs_running={payload['jobs_running']} jobs_total={payload['jobs_total']}")
        Viewer(stdscr, "\n".join(lines)).display()
        return
    other = prompt_line(stdscr, "Compare with case path: ")
    if not other:
        return
    try:
        payload = knife_ops.compare_payload(case_path, Path(other))
    except ValueError as exc:
        _show_message(stdscr, str(exc))
        return
    lines = [
        f"left_case={payload['left_case']}",
        f"right_case={payload['right_case']}",
        f"diff_count={payload['diff_count']}",
    ]
    for diff in payload["diffs"]:
        lines.append("")
        lines.append(diff["rel_path"])
        if diff["error"]:
            lines.append(f"  error: {diff['error']}")
            continue
        if diff["missing_in_left"]:
            lines.append(f"  missing_in_left: {', '.join(diff['missing_in_left'])}")
        if diff["missing_in_right"]:
            lines.append(f"  missing_in_right: {', '.join(diff['missing_in_right'])}")
    Viewer(stdscr, "\n".join(lines)).display()


def _plot_screen(stdscr: Any, case_path: Path) -> None:
    labels = [
        "Metrics (latest solver log)",
        "Residuals (latest solver log)",
        "Back",
    ]
    menu = build_menu(stdscr, "CLI tools: plot", labels, menu_key="menu:cli_tools_plot")
    choice = menu.navigate()
    if choice in (-1, len(labels) - 1):
        return
    if choice == 0:
        try:
            payload = plot_ops.metrics_payload(case_path)
        except ValueError as exc:
            _show_message(stdscr, str(exc))
            return
        exec_data = payload["execution_time"]
        lines = [
            f"log={payload['log']}",
            f"time_steps={payload['times']['count']} last={payload['times']['last']}",
            f"courant_count={payload['courant']['count']} max={payload['courant']['max']}",
            f"execution_points={exec_data['count']} last={exec_data['last']}",
            f"residual_fields={','.join(payload['residual_fields'])}",
        ]
        Viewer(stdscr, "\n".join(lines)).display()
        return
    try:
        payload = plot_ops.residuals_payload(case_path)
    except ValueError as exc:
        _show_message(stdscr, str(exc))
        return
    if not payload["fields"]:
        _show_message(stdscr, f"No residuals found in {payload['log']}")
        return
    lines = [f"log={payload['log']}", ""]
    for row in payload["fields"]:
        lines.append(
            f"{row['field']}: count={row['count']} last={row['last']:.6g} "
            f"min={row['min']:.6g} max={row['max']:.6g}",
        )
    Viewer(stdscr, "\n".join(lines)).display()


def _watch_screen(stdscr: Any, case_path: Path) -> None:
    labels = [
        "Jobs (running)",
        "Jobs (all)",
        "Tail solver log",
        "Back",
    ]
    menu = build_menu(stdscr, "CLI tools: watch", labels, menu_key="menu:cli_tools_watch")
    choice = menu.navigate()
    if choice in (-1, len(labels) - 1):
        return
    if choice in (0, 1):
        try:
            payload = watch_ops.jobs_payload(case_path, include_all=choice == 1)
        except ValueError as exc:
            _show_message(stdscr, str(exc))
            return
        lines = [f"case={payload['case']}", f"count={payload['count']}", ""]
        if not payload["jobs"]:
            lines.append("No tracked jobs.")
        else:
            for job in payload["jobs"]:
                lines.append(
                    f"{job.get('name', 'job')} pid={job.get('pid', '?')} "
                    f"status={job.get('status', 'unknown')}",
                )
        Viewer(stdscr, "\n".join(lines)).display()
        return

    try:
        payload = watch_ops.log_tail_payload(case_path, lines=80)
    except ValueError as exc:
        _show_message(stdscr, str(exc))
        return
    lines = [f"log={payload['log']}", "", *payload["lines"]]
    Viewer(stdscr, "\n".join(lines)).display()


def _run_screen(stdscr: Any, case_path: Path) -> None:  # noqa: C901, PLR0911
    labels = [
        "List tools",
        "Export tools JSON",
        "Run tool",
        "Run solver",
        "Run solver in background",
        "Back",
    ]
    menu = build_menu(stdscr, "CLI tools: run", labels, menu_key="menu:cli_tools_run")
    choice = menu.navigate()
    if choice in (-1, len(labels) - 1):
        return
    if choice == 0:
        try:
            payload = run_ops.tool_catalog_payload(case_path)
        except ValueError as exc:
            _show_message(stdscr, str(exc))
            return
        names = [str(item) for item in payload["tools"]]
        Viewer(stdscr, "\n".join(names) if names else "No tools available.").display()
        return
    if choice == 1:
        _export_tool_catalog_json(stdscr, case_path)
        return
    if choice == 2:
        name = prompt_line(stdscr, "Tool name: ")
        if not name:
            return
        try:
            resolved = run_ops.resolve_tool(case_path, name)
        except ValueError as exc:
            _show_message(stdscr, str(exc))
            return
        if resolved is None:
            _show_message(stdscr, f"Unknown tool: {name}")
            return
        display_name, cmd = resolved
        _show_run_result(stdscr, case_path, display_name, cmd, background=False)
        return

    parallel = 0
    parallel_text = prompt_line(stdscr, "Parallel np (blank for serial): ")
    if parallel_text:
        try:
            parallel = int(parallel_text)
        except ValueError:
            _show_message(stdscr, f"Invalid parallel value: {parallel_text}")
            return

    try:
        display, cmd = run_ops.solver_command(case_path, parallel=parallel)
    except ValueError as exc:
        _show_message(stdscr, str(exc))
        return
    _show_run_result(stdscr, case_path, display, cmd, background=(choice == 4))


def _export_tool_catalog_json(stdscr: Any, case_path: Path) -> None:
    output_text = prompt_line(stdscr, "Output path (.ofti/tool_catalog.json): ")
    if output_text is None:
        return
    destination = Path(output_text) if output_text else Path(".ofti/tool_catalog.json")
    try:
        export_path = run_ops.write_tool_catalog_json(case_path, output_path=destination)
    except (OSError, ValueError) as exc:
        _show_message(stdscr, f"Failed to export tool catalog: {exc}")
        return
    try:
        payload = run_ops.tool_catalog_payload(case_path)
    except ValueError:
        payload = None
    if payload is None:
        _show_message(stdscr, f"Exported tool catalog: {export_path}")
        return
    _show_message(
        stdscr,
        f"Exported {len(payload['tools'])} tools to {export_path}\n"
        f"{json.dumps(payload, indent=2, sort_keys=True)}",
    )


def _show_run_result(
    stdscr: Any,
    case_path: Path,
    display_name: str,
    cmd: list[str],
    *,
    background: bool,
) -> None:
    result = run_ops.execute_case_command(
        case_path,
        display_name,
        cmd,
        background=background,
    )
    if result.pid is not None:
        _show_message(
            stdscr,
            f"Started {display_name} in background: pid={result.pid} log={result.log_path}",
        )
        return
    lines = [
        f"$ {' '.join(cmd)}",
        "",
        f"returncode={result.returncode}",
        "",
        "stdout:",
        result.stdout or "(empty)",
        "",
        "stderr:",
        result.stderr or "(empty)",
    ]
    Viewer(stdscr, "\n".join(lines)).display()


def cli_knife_screen(stdscr: Any, case_path: Path) -> None:
    _knife_screen(stdscr, case_path)


def cli_plot_screen(stdscr: Any, case_path: Path) -> None:
    _plot_screen(stdscr, case_path)


def cli_watch_screen(stdscr: Any, case_path: Path) -> None:
    _watch_screen(stdscr, case_path)


def cli_run_screen(stdscr: Any, case_path: Path) -> None:
    _run_screen(stdscr, case_path)

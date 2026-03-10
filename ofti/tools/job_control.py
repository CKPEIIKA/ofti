from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any

from ofti.foam.config import get_config
from ofti.tools import watch_service
from ofti.tools.cli_tools import run as run_ops
from ofti.tools.helpers import resolve_openfoam_bashrc
from ofti.tools.input_prompts import prompt_command_line
from ofti.tools.menu_helpers import build_menu
from ofti.tools.runner import (
    _expand_command,
    _expand_shell_command,
    _show_message,
    _with_no_foam_hint,
)


def run_tool_background_screen(stdscr: Any, case_path: Path) -> None:
    options = _background_tool_catalog(case_path)
    labels = [name for name, _cmd in options] + ["Back"]
    menu = build_menu(
        stdscr,
        "Run tool in background",
        labels,
        menu_key="menu:job_start",
    )
    choice = menu.navigate()
    if choice == -1 or choice == len(labels) - 1:
        return
    name, cmd = options[choice]
    if name == "[custom] command":
        cmd = prompt_command_line(stdscr, "Command line: ")
        if cmd is None:
            return
        name = cmd[0]
    _start_background_command(stdscr, case_path, name, cmd)


def stop_job_screen(stdscr: Any, case_path: Path) -> None:
    jobs = _running_jobs(case_path)
    if not jobs:
        _show_message(stdscr, "No running jobs to stop.")
        return
    labels = [_job_label(job) for job in jobs] + ["Back"]
    menu = build_menu(
        stdscr,
        "Stop job",
        labels,
        menu_key="menu:job_stop",
    )
    choice = menu.navigate()
    if choice == -1 or choice == len(labels) - 1:
        return
    job = jobs[choice]
    payload = watch_service.stop_payload(
        case_path,
        job_id=str(job.get("id", "")),
        name=None,
        all_jobs=False,
        kind="any",
        signal_name="TERM",
    )
    failed = list(payload.get("failed", []))
    stopped = list(payload.get("stopped", []))
    if failed:
        row = failed[0]
        _show_message(
            stdscr,
            f"Failed to stop pid {row.get('pid', '?')}: {row.get('error', 'unknown')}",
        )
        return
    if stopped:
        row = stopped[0]
        _show_message(stdscr, f"Sent SIGTERM to pid {row.get('pid', '?')}.")
        return
    _show_message(stdscr, "No job stopped.")


def _background_tool_catalog(case_path: Path) -> list[tuple[str, list[str]]]:
    base: list[tuple[str, list[str]]] = []
    try:
        payload = run_ops.tool_catalog_payload(case_path)
    except ValueError:
        payload = {"tools": []}
    for display in payload["tools"]:
        resolved = run_ops.resolve_tool(case_path, display)
        if resolved is None:
            continue
        base.append((resolved[0], resolved[1]))
    custom = [("[custom] command", [])]
    return base + custom


def _start_background_command(
    stdscr: Any,
    case_path: Path,
    name: str,
    cmd: list[str],
) -> None:
    expanded = _expand_command(cmd, case_path)
    wm_dir = os.environ.get("WM_PROJECT_DIR")
    if wm_dir and get_config().use_runfunctions:
        cmd_str = " ".join(shlex.quote(part) for part in expanded)
        shell_cmd = f'. "{wm_dir}/bin/tools/RunFunctions"; runApplication {cmd_str}'
        _start_background_shell(stdscr, case_path, name, shell_cmd)
        return

    bashrc = resolve_openfoam_bashrc()
    if bashrc:
        shell_cmd = " ".join(shlex.quote(part) for part in expanded)
        _start_background_shell(stdscr, case_path, name, shell_cmd)
        return

    try:
        payload = watch_service.start_payload(
            case_path,
            name=name,
            command=expanded,
            detached=True,
            log_file=str(_log_path(case_path, name)),
            kind="solver",
        )
    except ValueError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run {name}: {exc}"))
        return
    _show_message(
        stdscr,
        f"Started {name} (pid {payload.get('pid', '?')}).",
    )


def start_tool_background(stdscr: Any, case_path: Path, name: str, cmd: list[str]) -> None:
    _start_background_command(stdscr, case_path, name, cmd)


def _start_background_shell(
    stdscr: Any,
    case_path: Path,
    name: str,
    shell_cmd: str,
) -> None:
    shell_cmd = _expand_shell_command(shell_cmd, case_path)
    try:
        payload = watch_service.start_payload(
            case_path,
            name=name,
            command=["bash", "--noprofile", "--norc", "-c", shell_cmd],
            detached=True,
            log_file=str(_log_path(case_path, name)),
            kind="solver",
        )
    except ValueError as exc:
        _show_message(stdscr, _with_no_foam_hint(f"Failed to run {name}: {exc}"))
        return
    _show_message(
        stdscr,
        f"Started {name} (pid {payload.get('pid', '?')}).",
    )


def pause_job_screen(stdscr: Any, case_path: Path) -> None:
    _job_action_screen(
        stdscr,
        case_path,
        title="Pause job",
        success_prefix="Paused",
        run_action=lambda selected: watch_service.pause_payload(
            case_path,
            job_id=selected,
            all_jobs=False,
            kind="any",
        ),
        key="paused",
        empty_message="No running jobs to pause.",
    )


def resume_job_screen(stdscr: Any, case_path: Path) -> None:
    _job_action_screen(
        stdscr,
        case_path,
        title="Resume job",
        success_prefix="Resumed",
        run_action=lambda selected: watch_service.resume_payload(
            case_path,
            job_id=selected,
            all_jobs=False,
            kind="any",
        ),
        key="resumed",
        empty_message="No running jobs to resume.",
    )


def _running_jobs(case_path: Path) -> list[dict[str, Any]]:
    rows = [watch_service._job_with_schema(case_path, job) for job in watch_service.refresh_jobs(case_path)]
    return [job for job in rows if bool(job.get("running"))]


def _job_label(job: dict[str, Any]) -> str:
    return (
        f"{job.get('name', 'job')} pid={job.get('pid', '?')} "
        f"status={job.get('status', 'unknown')}"
    )


def _job_action_screen(
    stdscr: Any,
    case_path: Path,
    *,
    title: str,
    success_prefix: str,
    run_action,
    key: str,
    empty_message: str,
) -> None:
    jobs = _running_jobs(case_path)
    if not jobs:
        _show_message(stdscr, empty_message)
        return
    labels = [_job_label(job) for job in jobs] + ["Back"]
    menu = build_menu(stdscr, title, labels, menu_key=f"menu:{_sanitize_title(title)}")
    choice = menu.navigate()
    if choice == -1 or choice == len(labels) - 1:
        return
    selected = str(jobs[choice].get("id", ""))
    payload = run_action(selected)
    failed = list(payload.get("failed", []))
    changed = list(payload.get(key, []))
    if failed:
        row = failed[0]
        _show_message(
            stdscr,
            f"Failed to update pid {row.get('pid', '?')}: {row.get('error', 'unknown')}",
        )
        return
    if changed:
        row = changed[0]
        _show_message(stdscr, f"{success_prefix} pid {row.get('pid', '?')}.")
        return
    _show_message(stdscr, "No job updated.")


def _sanitize_title(title: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in title).strip("_")


def _log_path(case_path: Path, name: str) -> Path:
    safe = "".join(ch for ch in name if ch.isalnum() or ch in ("-", "_", "."))
    return case_path / f"log.{safe or 'tool'}"

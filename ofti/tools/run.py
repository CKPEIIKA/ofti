from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.core.case import read_number_of_subdomains
from ofti.core.checkmesh import format_checkmesh_summary
from ofti.core.templates import write_example_template
from ofti.core.tool_output import CommandResult, format_command_result, format_log_blob
from ofti.foam.config import key_hint
from ofti.foam.subprocess_utils import run_trusted
from ofti.tools.runner import (
    _record_tool_status,
    _show_message,
    _with_no_foam_hint,
    _write_tool_log,
)
from ofti.ui_curses.layout import status_message
from ofti.ui_curses.viewer import Viewer


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


def _decomposed_processors(case_path: Path) -> list[Path]:
    return sorted(p for p in case_path.iterdir() if p.is_dir() and p.name.startswith("processor"))

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ofti.core.tool_output import format_log_blob
from ofti.foam.config import get_config, key_hint
from ofti.foam.subprocess_utils import run_trusted
from ofti.tools.cleaning_utils import _ascii_kv_table, _run_shell_capture
from ofti.tools.helpers import resolve_openfoam_bashrc
from ofti.tools.runner import _show_message, _write_tool_log
from ofti.ui.status import status_message
from ofti.ui_curses.viewer import Viewer


def yplus_screen(stdscr: Any, case_path: Path) -> None:
    """Run yPlus and show min/max/avg summary with optional raw output."""
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

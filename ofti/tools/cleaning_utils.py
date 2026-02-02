from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ofti.foam.subprocess_utils import run_trusted
from ofti.tools.helpers import with_bashrc
from ofti.tools.runner import _expand_shell_command, _show_message


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


def _require_wm_project_dir(stdscr: Any) -> str | None:
    wm_dir = os.environ.get("WM_PROJECT_DIR")
    if wm_dir:
        return wm_dir
    _show_message(stdscr, "OpenFOAM environment not detected.")
    return None


def _ascii_kv_table(title: str, rows: list[tuple[str, str]]) -> str:
    if not rows:
        return title
    left_width = max(len(label) for label, _value in rows)
    right_width = max(len(value) for _label, value in rows)
    header_width = max(len(title), left_width + right_width + 3)
    left_width = max(left_width, header_width - right_width - 3)

    top = "+" + "-" * (left_width + 2) + "+" + "-" * (right_width + 2) + "+"
    title_line = f"| {title:<{left_width + right_width + 1}} |"
    sep = "+" + "-" * (left_width + 2) + "+" + "-" * (right_width + 2) + "+"
    body = [
        f"| {label:<{left_width}} | {value:<{right_width}} |" for label, value in rows
    ]
    return "\n".join([top, title_line, sep, *body, top])

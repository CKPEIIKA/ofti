from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.foam.subprocess_utils import run_trusted
from ofti.foamlib import adapter as foamlib_integration
from ofti.tools.runner import _show_message
from ofti.ui_curses.inputs import prompt_input
from ofti.ui_curses.viewer import Viewer


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
    case_path: Path,
    helper_cmd: list[str] | None,
    path: Path,
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
    header_lines: list[str] = []
    if foamlib_integration.is_foam_file(path):
        try:
            keys = foamlib_integration.list_keywords(path)
            if keys:
                header_lines = [
                    "Keys:",
                    "  " + ", ".join(keys),
                    "",
                ]
        except Exception:
            header_lines = []
    viewer = Viewer(stdscr, "\n".join(header_lines) + content)
    viewer.display()


def _prompt_line(stdscr: Any, prompt: str) -> str:
    stdscr.clear()
    value = prompt_input(stdscr, prompt)
    if value is None:
        return ""
    return value.strip()

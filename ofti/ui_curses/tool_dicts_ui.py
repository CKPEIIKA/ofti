from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.core.tool_dicts_service import ensure_dict
from ofti.foamlib import adapter as foamlib_integration
from ofti.tools.runner import _show_message
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

    result = ensure_dict(
        case_path,
        name,
        path,
        helper_cmd,
        generate=True,
    )
    return result.created


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

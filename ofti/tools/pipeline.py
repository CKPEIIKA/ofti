from __future__ import annotations

import curses
import shlex
from contextlib import suppress
from pathlib import Path
from typing import Any

from ofti.core.case import detect_solver
from ofti.foam.subprocess_utils import run_trusted
from ofti.tools.runner import _show_message, load_postprocessing_presets, load_tool_presets
from ofti.ui_curses.layout import status_message
from ofti.ui_curses.menus import Menu
from ofti.ui_curses.viewer import Viewer

PIPELINE_FILENAME = "Allrun"
PIPELINE_HEADER = "# OFTI-PIPELINE"


def pipeline_runner_screen(stdscr: Any, case_path: Path) -> None:
    pipeline_path = case_path / PIPELINE_FILENAME
    if not pipeline_path.is_file():
        _show_message(stdscr, f"{PIPELINE_FILENAME} not found in case directory.")
        return
    commands, errors = _read_pipeline_commands(pipeline_path)
    if errors:
        lines = ["PIPELINE PARSE ERRORS", "", *errors]
        Viewer(stdscr, "\n".join(lines)).display()
        return
    if not commands:
        _show_message(stdscr, f"No commands found in {PIPELINE_FILENAME}.")
        return
    _run_pipeline_commands(stdscr, case_path, commands)


def pipeline_editor_screen(stdscr: Any, case_path: Path) -> None:  # noqa: C901, PLR0912
    pipeline_path = case_path / PIPELINE_FILENAME
    if not pipeline_path.is_file():
        stdscr.clear()
        stdscr.addstr(f"{PIPELINE_FILENAME} not found.\n")
        stdscr.addstr(f"Press c to create with {PIPELINE_HEADER}, any other key to return.\n")
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (ord("c"), ord("C")):
            _write_pipeline_file(pipeline_path, [])
        else:
            return

    commands, errors = _read_pipeline_commands(pipeline_path)
    if errors and any("Missing" in err for err in errors):
        stdscr.clear()
        stdscr.addstr(f"{PIPELINE_FILENAME} is missing {PIPELINE_HEADER}.\n")
        stdscr.addstr("Press c to replace with an OFTI pipeline header, any other key to return.\n")
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (ord("c"), ord("C")):
            _write_pipeline_file(pipeline_path, [])
            commands = []
            errors = []
        else:
            return
    if errors:
        lines = ["PIPELINE PARSE ERRORS", "", *errors]
        Viewer(stdscr, "\n".join(lines)).display()
        return

    cursor = 0
    while True:
        _render_pipeline_editor(stdscr, commands, cursor)
        key = stdscr.getch()
        if key in (ord("h"), 27):  # ESC
            return
        if key in (curses.KEY_DOWN, ord("j")):
            if commands:
                cursor = min(len(commands) - 1, cursor + 1)
            continue
        if key in (curses.KEY_UP, ord("k")):
            if commands:
                cursor = max(0, cursor - 1)
            continue
        if key in (ord("a"),):
            choice = _pipeline_pick_tool(stdscr, case_path)
            if choice is not None:
                insert_at = cursor + 1 if commands else 0
                commands.insert(insert_at, choice)
                cursor = insert_at
                _write_pipeline_file(pipeline_path, commands)
            continue
        if key in (ord("d"),):
            if commands:
                commands.pop(cursor)
                if cursor >= len(commands):
                    cursor = max(0, len(commands) - 1)
                _write_pipeline_file(pipeline_path, commands)
            continue
        if key in (ord("u"),):
            if commands and cursor > 0:
                commands[cursor - 1], commands[cursor] = commands[cursor], commands[cursor - 1]
                cursor -= 1
                _write_pipeline_file(pipeline_path, commands)
            continue
        if key in (ord("n"),):
            if commands and cursor < len(commands) - 1:
                commands[cursor + 1], commands[cursor] = commands[cursor], commands[cursor + 1]
                cursor += 1
                _write_pipeline_file(pipeline_path, commands)
            continue
        if key in (ord("r"),):
            if commands:
                _run_pipeline_commands(stdscr, case_path, commands)
            else:
                _show_message(stdscr, "Pipeline has no steps.")
            continue


def _run_pipeline_commands(
    stdscr: Any, case_path: Path, commands: list[list[str]],
) -> None:
    results: list[str] = []
    for idx, cmd in enumerate(commands, start=1):
        status_message(stdscr, f"Pipeline {idx}/{len(commands)}: {' '.join(cmd)}")
        try:
            result = run_trusted(
                cmd,
                cwd=case_path,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            results.append(f"$ {' '.join(cmd)}")
            results.append(f"status: ERROR ({exc})")
            break
        status = "OK" if result.returncode == 0 else f"ERROR ({result.returncode})"
        results.append(f"$ {' '.join(cmd)}")
        results.append(f"status: {status}")
        if result.stdout:
            results.append("stdout:")
            results.append(_tail_text(result.stdout))
        if result.stderr:
            results.append("stderr:")
            results.append(_tail_text(result.stderr))
        results.append("")
        if result.returncode != 0:
            break

    Viewer(stdscr, "\n".join(results).strip()).display()


def _read_pipeline_commands(path: Path) -> tuple[list[list[str]], list[str]]:
    commands: list[list[str]] = []
    errors: list[str] = []
    try:
        lines = path.read_text(errors="ignore").splitlines()
    except OSError as exc:
        return [], [f"Failed to read {path.name}: {exc}"]
    header_index = None
    for idx, raw in enumerate(lines):
        if raw.strip() == PIPELINE_HEADER:
            header_index = idx
            break
    if header_index is None:
        return [], [f"Missing {PIPELINE_HEADER} header in {path.name}."]
    for line_no, raw in enumerate(lines[header_index + 1 :], start=header_index + 2):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parts = shlex.split(line)
        except ValueError as exc:
            errors.append(f"Line {line_no}: {exc}")
            continue
        if not parts:
            continue
        commands.append(parts)
    return commands, errors


def _write_pipeline_file(path: Path, commands: list[list[str]]) -> None:
    shebang = "#!/bin/bash"
    if path.is_file():
        try:
            first = path.read_text(errors="ignore").splitlines()[:1]
        except OSError:
            first = []
        if first and first[0].startswith("#!"):
            shebang = first[0].strip()
    lines = [shebang, PIPELINE_HEADER, ""]
    for cmd in commands:
        rendered = " ".join(shlex.quote(part) for part in cmd)
        lines.append(rendered)
    content = "\n".join(lines).rstrip() + "\n"
    path.write_text(content)


def _pipeline_tool_catalog(case_path: Path) -> list[tuple[str, list[str]]]:
    base = [
        ("blockMesh", ["blockMesh"]),
        ("checkMesh", ["checkMesh"]),
        ("setFields", ["setFields"]),
        ("topoSet", ["topoSet"]),
        ("snappyHexMesh", ["snappyHexMesh"]),
        ("decomposePar", ["decomposePar"]),
        ("reconstructPar", ["reconstructPar"]),
        ("postProcess -latestTime", ["postProcess", "-latestTime"]),
        ("foamCalc", ["foamCalc"]),
    ]
    solver = detect_solver(case_path)
    if solver and solver != "unknown":
        base.append((f"runSolver ({solver})", [solver]))
    extra = load_tool_presets(case_path)
    post = [(f"[post] {name}", cmd) for name, cmd in load_postprocessing_presets(case_path)]
    return base + extra + post


def _pipeline_pick_tool(stdscr: Any, case_path: Path) -> list[str] | None:
    options = _pipeline_tool_catalog(case_path)
    labels = [name for name, _cmd in options] + ["Back"]
    menu = Menu(stdscr, "Add pipeline step", labels)
    choice = menu.navigate()
    if choice == -1 or choice == len(labels) - 1:
        return None
    _name, cmd = options[choice]
    return list(cmd)


def _render_pipeline_editor(
    stdscr: Any, commands: list[list[str]], cursor: int,
) -> None:
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    header = f"Pipeline editor ({PIPELINE_FILENAME})"
    controls = "a:add  d:delete  u:up  n:down  r:run  h/esc:back"
    try:
        stdscr.addstr(0, 0, header[: max(1, width - 1)])
        stdscr.addstr(1, 0, PIPELINE_HEADER[: max(1, width - 1)])
        stdscr.addstr(2, 0, controls[: max(1, width - 1)])
    except curses.error:
        return
    start_row = 4
    available = max(0, height - start_row)
    if not commands:
        with suppress(curses.error):
            stdscr.addstr(start_row, 0, "(empty pipeline)"[: max(1, width - 1)])
        stdscr.refresh()
        return
    cursor = max(0, min(cursor, len(commands) - 1))
    scroll = max(0, min(cursor, max(0, len(commands) - available)))
    for idx in range(scroll, min(len(commands), scroll + available)):
        prefix = ">> " if idx == cursor else "   "
        label = " ".join(shlex.quote(part) for part in commands[idx])
        line = f"{prefix}{label}"
        try:
            if idx == cursor:
                stdscr.attron(curses.color_pair(1))
                stdscr.addstr(start_row + idx - scroll, 0, line[: max(1, width - 1)])
                stdscr.attroff(curses.color_pair(1))
            else:
                stdscr.addstr(start_row + idx - scroll, 0, line[: max(1, width - 1)])
        except curses.error:
            pass
    stdscr.refresh()


def _tail_text(text: str, max_lines: int = 20) -> str:
    lines = text.strip().splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines) if lines else "(empty)"
    tail = "\n".join(lines[-max_lines:])
    return f"... ({len(lines) - max_lines} lines omitted)\n{tail}"

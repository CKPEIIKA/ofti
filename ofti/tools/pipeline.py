from __future__ import annotations

import curses
import shlex
from contextlib import suppress
from pathlib import Path
from typing import Any

from ofti.core import pipeline as pipeline_service
from ofti.tools.input_prompts import prompt_args_line, prompt_command_line, prompt_line
from ofti.tools.menu_helpers import build_menu
from ofti.tools.runner import _show_message
from ofti.tools.tool_catalog import tool_catalog
from ofti.ui_curses.layout import status_message
from ofti.ui_curses.viewer import Viewer

PIPELINE_FILENAME = pipeline_service.PIPELINE_FILENAME
PIPELINE_HEADER = pipeline_service.PIPELINE_HEADER
PIPELINE_SET_COMMAND = pipeline_service.PIPELINE_SET_COMMAND


def pipeline_runner_screen(stdscr: Any, case_path: Path) -> None:
    pipeline_path = case_path / PIPELINE_FILENAME
    if not pipeline_path.is_file():
        _show_message(stdscr, f"{PIPELINE_FILENAME} not found in case directory.")
        return
    commands, errors = pipeline_service.read_pipeline_commands(pipeline_path)
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
            pipeline_service.write_pipeline_file(pipeline_path, [])
        else:
            return

    commands, errors = pipeline_service.read_pipeline_commands(pipeline_path)
    if errors and any("Missing" in err for err in errors):
        stdscr.clear()
        stdscr.addstr(f"{PIPELINE_FILENAME} is missing {PIPELINE_HEADER}.\n")
        stdscr.addstr("Press c to replace with an OFTI pipeline header, any other key to return.\n")
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (ord("c"), ord("C")):
            pipeline_service.write_pipeline_file(pipeline_path, [])
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
                pipeline_service.write_pipeline_file(pipeline_path, commands)
            continue
        if key in (ord("e"),):
            if not commands:
                continue
            current = " ".join(shlex.quote(part) for part in commands[cursor])
            edited = prompt_line(stdscr, f"Edit command: {current}\n> ")
            if edited is None:
                continue
            if not edited:
                continue
            try:
                parts = shlex.split(edited)
            except ValueError:
                _show_message(stdscr, "Invalid command line.")
                continue
            commands[cursor] = parts
            pipeline_service.write_pipeline_file(pipeline_path, commands)
            continue
        if key in (ord("d"),):
            if commands:
                commands.pop(cursor)
                if cursor >= len(commands):
                    cursor = max(0, len(commands) - 1)
                pipeline_service.write_pipeline_file(pipeline_path, commands)
            continue
        if key in (ord("u"),):
            if commands and cursor > 0:
                commands[cursor - 1], commands[cursor] = commands[cursor], commands[cursor - 1]
                cursor -= 1
                pipeline_service.write_pipeline_file(pipeline_path, commands)
            continue
        if key in (ord("n"),):
            if commands and cursor < len(commands) - 1:
                commands[cursor + 1], commands[cursor] = commands[cursor], commands[cursor + 1]
                cursor += 1
                pipeline_service.write_pipeline_file(pipeline_path, commands)
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
    results = pipeline_service.run_pipeline_commands(
        case_path,
        commands,
        status_cb=lambda msg: status_message(stdscr, msg),
    )
    Viewer(stdscr, "\n".join(results).strip()).display()


def _pipeline_tool_catalog(case_path: Path) -> list[tuple[str, list[str]]]:
    base = tool_catalog(case_path)
    custom = [
        ("[config] set entry", [PIPELINE_SET_COMMAND]),
        ("[custom] echo", ["echo"]),
        ("[custom] command", []),
    ]
    return base + custom


def _pipeline_pick_tool(stdscr: Any, case_path: Path) -> list[str] | None:  # noqa: C901, PLR0911
    options = _pipeline_tool_catalog(case_path)
    labels = [name for name, _cmd in options] + ["Back"]
    menu = build_menu(
        stdscr,
        "Add pipeline step",
        labels,
        menu_key="menu:pipeline_add",
        item_hint="Add selected step.",
    )
    choice = menu.navigate()
    if choice == -1 or choice == len(labels) - 1:
        return None
    name, cmd = options[choice]
    if name == "[config] set entry":
        rel_path = prompt_line(stdscr, "Config file (e.g., system/controlDict): ")
        if rel_path is None or not rel_path.strip():
            return None
        key = prompt_line(stdscr, "Key path (dot separated): ")
        if key is None or not key.strip():
            return None
        value = prompt_line(stdscr, "Value: ")
        if value is None:
            return None
        return [PIPELINE_SET_COMMAND, rel_path.strip(), key.strip(), value]
    if name == "[custom] echo":
        text = prompt_line(stdscr, "Echo text: ")
        if text is None:
            return None
        return ["echo", text] if text else ["echo"]
    if name == "[custom] command":
        cmd = prompt_command_line(stdscr, "Command line: ")
        if cmd is None:
            return None
        return cmd

    cmd = list(cmd)
    extra = prompt_args_line(stdscr, "Extra args (optional): ")
    if extra is None:
        return cmd
    if extra:
        cmd.extend(extra)
    return cmd


def _render_pipeline_editor(
    stdscr: Any, commands: list[list[str]], cursor: int,
) -> None:
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    header = f"Pipeline editor ({PIPELINE_FILENAME})"
    controls = "a:add  e:edit  d:delete  u:up  n:down  r:run  h/esc:back"
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


 

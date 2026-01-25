from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ofti.foam.openfoam import OpenFOAMError
from ofti.foam.openfoam_env import ensure_environment
from ofti.tools import list_tool_commands, run_tool_by_name


@dataclass(frozen=True)
class CommandCallbacks:
    check_syntax: Callable[[Any, Path, Any], None]
    tools_screen: Callable[[Any, Path], None]
    diagnostics_screen: Callable[[Any, Path], None]
    run_current_solver: Callable[[Any, Path], None]
    show_message: Callable[[Any, str], None]
    tasks_screen: Callable[[Any, Any], None]
    openfoam_env_screen: Callable[[Any], None]
    clone_case: Callable[[Any, Path, str | None], None]
    search_screen: Callable[[Any, Path, Any], None]


def command_suggestions(case_path: Path) -> list[str]:
    base = [
        "check",
        "tools",
        "diag",
        "run",
        "nofoam",
        "no-foam",
        "tasks",
        "cancel",
        "search",
        "foamenv",
        "clone",
        "quit",
        "help",
    ]
    tool_names = list_tool_commands(case_path)
    base += [f"tool {name}" for name in tool_names]
    base += [f"run {name}" for name in tool_names]
    base += tool_names
    return sorted(set(base))


def handle_command(
    stdscr: Any,
    case_path: Path,
    state: Any,
    command: str,
    callbacks: CommandCallbacks,
) -> str | None:
    cmd = command.strip()
    if cmd.startswith(":"):
        cmd = cmd[1:].strip()
    if not cmd:
        return None

    parts = cmd.split()
    name = parts[0].lower()
    normalized = name.replace("-", "").replace("_", "")
    if getattr(state, "no_foam", False):
        blocked = {
            "check",
            "syntax",
            "tools",
            "tool",
            "diag",
            "diagnostics",
            "run",
            "solver",
            "search",
            "find",
        }
        if name in blocked or cmd in list_tool_commands(case_path):
            callbacks.show_message(
                stdscr,
                "OpenFOAM environment not found; tool commands are disabled in limited mode.",
            )
            return "handled"
    if name in ("q", "quit", "exit"):
        return "quit"
    if name in ("check", "syntax"):
        callbacks.check_syntax(stdscr, case_path, state)
        return "handled"
    if name in ("tools", "tool"):
        if len(parts) > 1:
            tool_name = " ".join(parts[1:])
            if run_tool_by_name(stdscr, case_path, tool_name):
                return "handled"
            callbacks.show_message(stdscr, f"Unknown tool: {tool_name}")
            return "handled"
        callbacks.tools_screen(stdscr, case_path)
        return "handled"
    if name in ("diag", "diagnostics"):
        callbacks.diagnostics_screen(stdscr, case_path)
        return "handled"
    if name in ("search", "find"):
        callbacks.search_screen(stdscr, case_path, state)
        return "handled"
    if name in ("foamenv", "foam-env", "openfoam-env"):
        callbacks.openfoam_env_screen(stdscr)
        return "handled"
    if name in ("clone", "copy"):
        target = " ".join(parts[1:]) if len(parts) > 1 else None
        callbacks.clone_case(stdscr, case_path, target)
        return "handled"
    if name in ("tasks", "task"):
        callbacks.tasks_screen(stdscr, state)
        return "handled"
    if name in ("cancel", "stop"):
        if len(parts) < 2:
            callbacks.show_message(stdscr, "Usage: :cancel <task-name>")
            return "handled"
        task_name = " ".join(parts[1:])
        if task_name in ("check", "syntax"):
            task_name = "check_syntax"
        if hasattr(state, "tasks") and state.tasks.cancel(task_name):
            callbacks.show_message(stdscr, f"Requested cancel for {task_name}.")
            return "handled"
        callbacks.show_message(stdscr, f"No running task named {task_name}.")
        return "handled"
    if name in ("run", "solver"):
        if len(parts) > 1:
            tool_name = " ".join(parts[1:])
            if run_tool_by_name(stdscr, case_path, tool_name):
                return "handled"
            callbacks.show_message(stdscr, f"Unknown tool: {tool_name}")
            return "handled"
        callbacks.run_current_solver(stdscr, case_path)
        return "handled"
    if normalized in ("nofoam", "foam"):
        desired = None
        if len(parts) > 1:
            arg = parts[1].lower()
            if arg in ("on", "true", "1", "yes"):
                desired = True
            elif arg in ("off", "false", "0", "no"):
                desired = False
        if desired is None:
            desired = not state.no_foam
        if not desired:
            try:
                ensure_environment()
            except OpenFOAMError as exc:
                callbacks.show_message(stdscr, f"Cannot enable foam mode: {exc}")
                state.no_foam = True
                return "handled"
        state.no_foam = desired
        if state.no_foam:
            os.environ["OFTI_NO_FOAM"] = "1"
        else:
            os.environ.pop("OFTI_NO_FOAM", None)
        mode_label = "no-foam" if state.no_foam else "foam"
        callbacks.show_message(stdscr, f"Mode set to {mode_label}.")
        return "handled"
    if name in ("help", "?"):
        callbacks.show_message(
            stdscr,
            "Commands: :check, :tools, :diag, :run, :nofoam, :tasks, "
            ":search, :cancel <name>, :foamenv, :clone <name>, :tool <name>, :quit",
        )
        return "handled"

    if run_tool_by_name(stdscr, case_path, cmd):
        return "handled"

    callbacks.show_message(stdscr, f"Unknown command: {command}")
    return "handled"

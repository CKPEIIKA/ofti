from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ofti.app.helpers import set_no_foam_mode
from ofti.core.commands import CommandKind, is_blocked_in_no_foam, parse_command
from ofti.foam.openfoam import OpenFOAMError
from ofti.foam.openfoam_env import ensure_environment
from ofti.foamlib_adapter import available as foamlib_available
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
    action = parse_command(command, tool_names=list_tool_commands(case_path))
    if action is None:
        return None

    if getattr(state, "no_foam", False) and is_blocked_in_no_foam(action):
        if action.kind == CommandKind.CHECK and foamlib_available():
            pass
        else:
            callbacks.show_message(
                stdscr,
                "OpenFOAM environment not found; tool commands are disabled in limited mode.",
            )
            return "handled"
    if action.kind == CommandKind.QUIT:
        return "quit"
    if action.kind == CommandKind.CHECK:
        callbacks.check_syntax(stdscr, case_path, state)
        return "handled"
    if action.kind == CommandKind.TOOLS:
        callbacks.tools_screen(stdscr, case_path)
        return "handled"
    if action.kind == CommandKind.DIAGNOSTICS:
        callbacks.diagnostics_screen(stdscr, case_path)
        return "handled"
    if action.kind == CommandKind.SEARCH:
        callbacks.search_screen(stdscr, case_path, state)
        return "handled"
    if action.kind == CommandKind.FOAM_ENV:
        callbacks.openfoam_env_screen(stdscr)
        return "handled"
    if action.kind == CommandKind.CLONE:
        target = action.args[0] if action.args else None
        callbacks.clone_case(stdscr, case_path, target or None)
        return "handled"
    if action.kind == CommandKind.TASKS:
        callbacks.tasks_screen(stdscr, state)
        return "handled"
    if action.kind == CommandKind.CANCEL:
        if action.error:
            callbacks.show_message(stdscr, action.error)
            return "handled"
        task_name = action.args[0] if action.args else ""
        if task_name in ("check", "syntax"):
            task_name = "check_syntax"
        if hasattr(state, "tasks") and state.tasks.cancel(task_name):
            callbacks.show_message(stdscr, f"Requested cancel for {task_name}.")
            return "handled"
        callbacks.show_message(stdscr, f"No running task named {task_name}.")
        return "handled"
    if action.kind == CommandKind.RUN_SOLVER:
        callbacks.run_current_solver(stdscr, case_path)
        return "handled"
    if action.kind == CommandKind.RUN_TOOL:
        tool_name = action.args[0] if action.args else ""
        if run_tool_by_name(stdscr, case_path, tool_name):
            return "handled"
        callbacks.show_message(stdscr, f"Unknown tool: {tool_name}")
        return "handled"
    if action.kind == CommandKind.NO_FOAM:
        desired = action.desired
        if desired is None:
            desired = not state.no_foam
        if not desired:
            try:
                ensure_environment()
            except OpenFOAMError as exc:
                callbacks.show_message(stdscr, f"Cannot enable foam mode: {exc}")
                set_no_foam_mode(state, True, reason=str(exc))
                return "handled"
        set_no_foam_mode(state, desired, reason=None)
        mode_label = "no-foam" if state.no_foam else "foam"
        callbacks.show_message(stdscr, f"Mode set to {mode_label}.")
        return "handled"
    if action.kind == CommandKind.HELP:
        callbacks.show_message(
            stdscr,
            "Commands: :check, :tools, :diag, :run, :nofoam, :tasks, "
            ":search, :cancel <name>, :foamenv, :clone <name>, :tool <name>, :quit",
        )
        return "handled"

    if action.kind == CommandKind.UNKNOWN:
        callbacks.show_message(stdscr, f"Unknown command: {command}")
    return "handled"

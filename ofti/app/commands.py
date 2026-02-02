from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ofti.core.commands import CommandKind, is_blocked_in_no_foam, parse_command
from ofti.tools.menus import run_tool_by_name
from ofti.tools.runner import list_tool_commands


@dataclass(frozen=True)
class CommandCallbacks:
    check_syntax: Callable[[Any, Path, Any], None]
    tools_screen: Callable[[Any, Path, Any], None]
    diagnostics_screen: Callable[[Any, Path, Any], None]
    run_current_solver: Callable[[Any, Path, Any], None]
    show_message: Callable[[Any, str], None]
    tasks_screen: Callable[[Any, Any], None]
    openfoam_env_screen: Callable[[Any], None]
    clone_case: Callable[[Any, Path, str | None], None]
    search_screen: Callable[[Any, Path, Any], None]
    terminal: Callable[[Any, Path, str | None], None]
    mesh_menu: Callable[[Any, Path, Any], None]
    physics_menu: Callable[[Any, Path, Any], None]
    simulation_menu: Callable[[Any, Path, Any], None]
    postprocessing_menu: Callable[[Any, Path, Any], None]
    clean_menu: Callable[[Any, Path, Any], None]
    clean_all: Callable[[Any, Path], None]
    config_menu: Callable[[Any, Path, Any], None]
    config_editor: Callable[[Any, Path, Any], None]
    config_create: Callable[[Any, Path], None]
    config_search: Callable[[Any, Path, Any], None]
    config_check: Callable[[Any, Path, Any], None]


def command_suggestions(case_path: Path) -> list[str]:
    base = [
        "check",
        "tools",
        "diag",
        "run",
        "tasks",
        "cancel",
        "search",
        "foamenv",
        "clone",
        "quit",
        "help",
        "term",
        "terminal",
        "mesh",
        "physics",
        "sim",
        "simulation",
        "post",
        "postprocessing",
        "clean",
        "clean-all",
        "config",
        "config-editor",
        "config-create",
        "config-search",
        "config-check",
        "config-env",
    ]
    tool_names = list_tool_commands(case_path)
    base += [f"tool {name}" for name in tool_names]
    base += [f"tool {name} -b" for name in tool_names]
    base += [f"run {name}" for name in tool_names]
    base += [f"{name} -b" for name in tool_names]
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

    if (
        getattr(state, "no_foam", False)
        and is_blocked_in_no_foam(action)
        and action.kind != CommandKind.CHECK
    ):
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
        callbacks.tools_screen(stdscr, case_path, state)
        return "handled"
    if action.kind == CommandKind.DIAGNOSTICS:
        callbacks.diagnostics_screen(stdscr, case_path, state)
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
        callbacks.run_current_solver(stdscr, case_path, state)
        return "handled"
    if action.kind == CommandKind.RUN_TOOL:
        tool_name = action.args[0] if action.args else ""
        if run_tool_by_name(
            stdscr,
            case_path,
            tool_name,
            background=action.background,
        ):
            return "handled"
        callbacks.show_message(stdscr, f"Unknown tool: {tool_name}")
        return "handled"
    if action.kind == CommandKind.TERMINAL:
        command_text = action.args[0] if action.args else ""
        callbacks.terminal(stdscr, case_path, command_text or None)
        return "handled"
    if action.kind == CommandKind.MESH:
        callbacks.mesh_menu(stdscr, case_path, state)
        return "handled"
    if action.kind == CommandKind.PHYSICS:
        callbacks.physics_menu(stdscr, case_path, state)
        return "handled"
    if action.kind == CommandKind.SIMULATION:
        callbacks.simulation_menu(stdscr, case_path, state)
        return "handled"
    if action.kind == CommandKind.POSTPROCESSING:
        callbacks.postprocessing_menu(stdscr, case_path, state)
        return "handled"
    if action.kind == CommandKind.CLEAN:
        callbacks.clean_menu(stdscr, case_path, state)
        return "handled"
    if action.kind == CommandKind.CLEAN_ALL:
        callbacks.clean_all(stdscr, case_path)
        return "handled"
    if action.kind == CommandKind.CONFIG:
        callbacks.config_menu(stdscr, case_path, state)
        return "handled"
    if action.kind == CommandKind.CONFIG_EDITOR:
        callbacks.config_editor(stdscr, case_path, state)
        return "handled"
    if action.kind == CommandKind.CONFIG_CREATE:
        callbacks.config_create(stdscr, case_path)
        return "handled"
    if action.kind == CommandKind.CONFIG_SEARCH:
        callbacks.config_search(stdscr, case_path, state)
        return "handled"
    if action.kind == CommandKind.CONFIG_CHECK:
        callbacks.config_check(stdscr, case_path, state)
        return "handled"
    if action.kind == CommandKind.TERMINAL:
        command_text = action.args[0] if action.args else ""
        callbacks.terminal(stdscr, case_path, command_text or None)
        return "handled"
    if action.kind == CommandKind.HELP:
        callbacks.show_message(
            stdscr,
            "Commands: :check, :tools, :diag, :run, :tasks, "
            ":search, :cancel <name>, :foamenv, :clone <name>, :tool <name>, :quit",
        )
        return "handled"

    if action.kind == CommandKind.UNKNOWN:
        callbacks.show_message(stdscr, f"Unknown command: {command}")
    return "handled"

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .openfoam import OpenFOAMError, ensure_environment
from .tools import run_tool_by_name, list_tool_commands


@dataclass(frozen=True)
class CommandCallbacks:
    check_syntax: Callable[[Any, Path, Any], None]
    tools_screen: Callable[[Any, Path], None]
    diagnostics_screen: Callable[[Any, Path], None]
    run_current_solver: Callable[[Any, Path], None]
    show_message: Callable[[Any, str], None]


def command_suggestions(case_path: Path) -> list[str]:
    base = ["check", "tools", "diag", "run", "nofoam", "no-foam", "quit", "help"]
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
) -> Optional[str]:
    cmd = command.strip()
    if cmd.startswith(":"):
        cmd = cmd[1:].strip()
    if not cmd:
        return None

    parts = cmd.split()
    name = parts[0].lower()
    normalized = name.replace("-", "").replace("_", "")
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
            os.environ["OF_TUI_NO_FOAM"] = "1"
        else:
            os.environ.pop("OF_TUI_NO_FOAM", None)
        mode_label = "no-foam" if state.no_foam else "foam"
        callbacks.show_message(stdscr, f"Mode set to {mode_label}.")
        return "handled"
    if name in ("help", "?"):
        callbacks.show_message(
            stdscr,
            "Commands: :check, :tools, :diag, :run, :nofoam, :tool <name>, :quit",
        )
        return "handled"

    if run_tool_by_name(stdscr, case_path, cmd):
        return "handled"

    callbacks.show_message(stdscr, f"Unknown command: {command}")
    return "handled"

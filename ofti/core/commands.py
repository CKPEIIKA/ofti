from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum


class CommandKind(str, Enum):
    QUIT = "quit"
    CHECK = "check"
    TOOLS = "tools"
    DIAGNOSTICS = "diagnostics"
    SEARCH = "search"
    FOAM_ENV = "foam_env"
    CLONE = "clone"
    TASKS = "tasks"
    CANCEL = "cancel"
    RUN_SOLVER = "run_solver"
    RUN_TOOL = "run_tool"
    NO_FOAM = "no_foam"
    HELP = "help"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CommandAction:
    kind: CommandKind
    raw: str
    args: tuple[str, ...] = ()
    desired: bool | None = None
    error: str | None = None


def _strip_command(command: str) -> str | None:
    cmd = command.strip()
    if cmd.startswith(":"):
        cmd = cmd[1:].strip()
    return cmd or None


def _simple_command(name: str, raw: str) -> CommandAction | None:
    simple_map = {
        "q": CommandKind.QUIT,
        "quit": CommandKind.QUIT,
        "exit": CommandKind.QUIT,
        "check": CommandKind.CHECK,
        "syntax": CommandKind.CHECK,
        "tools": CommandKind.TOOLS,
        "diag": CommandKind.DIAGNOSTICS,
        "diagnostics": CommandKind.DIAGNOSTICS,
        "search": CommandKind.SEARCH,
        "find": CommandKind.SEARCH,
        "foamenv": CommandKind.FOAM_ENV,
        "foam-env": CommandKind.FOAM_ENV,
        "openfoam-env": CommandKind.FOAM_ENV,
        "tasks": CommandKind.TASKS,
        "task": CommandKind.TASKS,
        "help": CommandKind.HELP,
        "?": CommandKind.HELP,
    }
    kind = simple_map.get(name)
    if kind is None:
        return None
    return CommandAction(kind, raw=raw)


def _tool_command(name: str, raw: str, parts: list[str]) -> CommandAction | None:
    if name == "tool":
        if len(parts) < 2:
            return CommandAction(
                CommandKind.TOOLS,
                raw=raw,
                error="Usage: :tool <name>",
            )
        return CommandAction(CommandKind.RUN_TOOL, raw=raw, args=(" ".join(parts[1:]),))
    if name in ("run", "solver"):
        if len(parts) > 1:
            return CommandAction(CommandKind.RUN_TOOL, raw=raw, args=(" ".join(parts[1:]),))
        return CommandAction(CommandKind.RUN_SOLVER, raw=raw)
    return None


def _cancel_command(name: str, raw: str, parts: list[str]) -> CommandAction | None:
    if name not in ("cancel", "stop"):
        return None
    if len(parts) < 2:
        return CommandAction(
            CommandKind.CANCEL,
            raw=raw,
            error="Usage: :cancel <task-name>",
        )
    task_name = " ".join(parts[1:])
    return CommandAction(CommandKind.CANCEL, raw=raw, args=(task_name,))


def _clone_command(name: str, raw: str, parts: list[str]) -> CommandAction | None:
    if name not in ("clone", "copy"):
        return None
    target = " ".join(parts[1:]) if len(parts) > 1 else ""
    return CommandAction(CommandKind.CLONE, raw=raw, args=(target,) if target else ())


def _no_foam_command(name: str, raw: str, parts: list[str]) -> CommandAction | None:
    normalized = name.replace("-", "").replace("_", "")
    if normalized not in ("nofoam", "foam"):
        return None
    desired: bool | None = None
    if len(parts) > 1:
        arg = parts[1].lower()
        if arg in ("on", "true", "1", "yes"):
            desired = True
        elif arg in ("off", "false", "0", "no"):
            desired = False
    return CommandAction(CommandKind.NO_FOAM, raw=raw, desired=desired)


def parse_command(command: str, tool_names: Iterable[str] | None = None) -> CommandAction | None:
    cmd = _strip_command(command)
    if not cmd:
        return None

    tool_set = set(tool_names or [])
    parts = cmd.split()
    name = parts[0].lower()

    action = _simple_command(name, cmd)
    if action is None:
        action = _tool_command(name, cmd, parts)
    if action is None:
        action = _cancel_command(name, cmd, parts)
    if action is None:
        action = _clone_command(name, cmd, parts)
    if action is None:
        action = _no_foam_command(name, cmd, parts)
    if action is None and cmd in tool_set:
        action = CommandAction(CommandKind.RUN_TOOL, raw=cmd, args=(cmd,))
    if action is None:
        action = CommandAction(CommandKind.UNKNOWN, raw=cmd)
    return action


def is_blocked_in_no_foam(action: CommandAction) -> bool:
    return action.kind in {
        CommandKind.CHECK,
        CommandKind.TOOLS,
        CommandKind.DIAGNOSTICS,
        CommandKind.SEARCH,
        CommandKind.RUN_SOLVER,
        CommandKind.RUN_TOOL,
    }

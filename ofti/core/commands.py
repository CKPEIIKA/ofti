from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class CommandKind(StrEnum):
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
    TERMINAL = "terminal"
    HELP = "help"
    MESH = "mesh"
    PHYSICS = "physics"
    SIMULATION = "simulation"
    POSTPROCESSING = "postprocessing"
    CLEAN = "clean"
    CLEAN_ALL = "clean_all"
    CONFIG = "config"
    CONFIG_EDITOR = "config_editor"
    CONFIG_CREATE = "config_create"
    CONFIG_SEARCH = "config_search"
    CONFIG_CHECK = "config_check"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CommandAction:
    kind: CommandKind
    raw: str
    args: tuple[str, ...] = ()
    error: str | None = None
    background: bool = False


def _strip_command(command: str) -> str | None:
    cmd = command.strip()
    if cmd.startswith(":"):
        cmd = cmd[1:].strip()
    return cmd or None


def _simple_command(name: str, raw: str) -> CommandAction | None:
    simple_map: dict[str, CommandKind] = {
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
        "mesh": CommandKind.MESH,
        "physics": CommandKind.PHYSICS,
        "sim": CommandKind.SIMULATION,
        "simulation": CommandKind.SIMULATION,
        "post": CommandKind.POSTPROCESSING,
        "postprocessing": CommandKind.POSTPROCESSING,
        "clean": CommandKind.CLEAN,
        "clean-all": CommandKind.CLEAN_ALL,
        "cleanall": CommandKind.CLEAN_ALL,
        "config": CommandKind.CONFIG,
        "config-editor": CommandKind.CONFIG_EDITOR,
        "configeditor": CommandKind.CONFIG_EDITOR,
        "config-edit": CommandKind.CONFIG_EDITOR,
        "config-create": CommandKind.CONFIG_CREATE,
        "configcreate": CommandKind.CONFIG_CREATE,
        "config-missing": CommandKind.CONFIG_CREATE,
        "config-search": CommandKind.CONFIG_SEARCH,
        "configsearch": CommandKind.CONFIG_SEARCH,
        "config-check": CommandKind.CONFIG_CHECK,
        "configcheck": CommandKind.CONFIG_CHECK,
        "config-env": CommandKind.FOAM_ENV,
        "configenv": CommandKind.FOAM_ENV,
        "runsolver": CommandKind.RUN_SOLVER,
    }
    kind = simple_map.get(name)
    if kind is None:
        return None
    return CommandAction(kind, raw=raw)


def _tool_command(
    name: str,
    raw: str,
    parts: list[str],
    background: bool,
    *,
    tool_set: set[str] | None = None,
) -> CommandAction | None:
    if name == "tool":
        return _explicit_tool_command(raw, parts, background)
    if name == "run":
        return _run_command(raw, parts, background, tool_set)
    if name == "solver":
        return _solver_command(raw, parts, background)
    return None


def _explicit_tool_command(raw: str, parts: list[str], background: bool) -> CommandAction:
    if len(parts) < 2:
        return CommandAction(CommandKind.TOOLS, raw=raw, error="Usage: :tool <name>")
    return _run_tool_action(raw, " ".join(parts[1:]), background)


def _run_command(
    raw: str,
    parts: list[str],
    background: bool,
    tool_set: set[str] | None,
) -> CommandAction:
    if len(parts) == 1:
        if tool_set is None or "run" not in tool_set:
            return CommandAction(CommandKind.RUN_SOLVER, raw=raw)
        return _run_tool_action(raw, "run", background)
    return _run_tool_action(raw, " ".join(parts[1:]), background)


def _solver_command(raw: str, parts: list[str], background: bool) -> CommandAction:
    if len(parts) == 1:
        return CommandAction(CommandKind.RUN_SOLVER, raw=raw)
    return _run_tool_action(raw, " ".join(parts[1:]), background)


def _run_tool_action(raw: str, arg: str, background: bool) -> CommandAction:
    return CommandAction(
        CommandKind.RUN_TOOL,
        raw=raw,
        args=(arg,),
        background=background,
    )


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


def _terminal_command(name: str, raw: str, parts: list[str]) -> CommandAction | None:
    if name not in ("term", "terminal"):
        return None
    payload = " ".join(parts[1:]).strip()
    return CommandAction(CommandKind.TERMINAL, raw=raw, args=(payload,))


def _extract_background_flag(parts: list[str]) -> tuple[list[str], bool]:
    if not parts:
        return parts, False
    if parts[-1] in ("-b", "--background"):
        return parts[:-1], True
    return parts, False


def parse_command(command: str, tool_names: Iterable[str] | None = None) -> CommandAction | None:
    cmd = _strip_command(command)
    if not cmd:
        return None
    if cmd.startswith("!"):
        payload = cmd[1:].lstrip()
        return CommandAction(CommandKind.TERMINAL, raw=cmd, args=(payload,))

    tool_set = set(tool_names or [])
    parts = cmd.split()
    sanitized_parts, background = _extract_background_flag(parts)
    if not sanitized_parts:
        return CommandAction(CommandKind.UNKNOWN, raw=cmd, background=background)
    name = sanitized_parts[0].lower()

    action = _named_command_action(name, cmd, sanitized_parts, background, tool_set)
    return action or CommandAction(CommandKind.UNKNOWN, raw=cmd)


def _named_command_action(
    name: str,
    cmd: str,
    parts: list[str],
    background: bool,
    tool_set: set[str],
) -> CommandAction | None:
    for resolver in (
        lambda: _simple_command(name, cmd),
        lambda: _tool_command(name, cmd, parts, background, tool_set=tool_set),
        lambda: _cancel_command(name, cmd, parts),
        lambda: _clone_command(name, cmd, parts),
        lambda: _terminal_command(name, cmd, parts),
        lambda: _tool_name_command(cmd, parts, background, tool_set),
    ):
        action = resolver()
        if action is not None:
            return action
    return None


def _tool_name_command(
    cmd: str,
    parts: list[str],
    background: bool,
    tool_set: set[str],
) -> CommandAction | None:
    cleaned_cmd = " ".join(parts)
    if cleaned_cmd not in tool_set:
        return None
    return CommandAction(
        CommandKind.RUN_TOOL,
        raw=cmd,
        args=(cleaned_cmd,),
        background=background,
    )


def is_blocked_in_no_foam(action: CommandAction) -> bool:
    return action.kind in {
        CommandKind.CHECK,
        CommandKind.TOOLS,
        CommandKind.DIAGNOSTICS,
        CommandKind.SEARCH,
        CommandKind.RUN_SOLVER,
        CommandKind.RUN_TOOL,
    }

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ofti.app.state import AppState
from ofti.app.tasks import running_tasks_status
from ofti.tools.runner import last_tool_status_line
from ofti.ui.help import menu_hint
from ofti.ui.menu import Menu


def menu_choice(
    stdscr: Any,
    title: str,
    options: list[str],
    state: AppState,
    menu_key: str,
    command_handler: Callable[[str], str | None] | None = None,
    command_suggestions: Callable[[], list[str]] | None = None,
    disabled_indices: set[int] | None = None,
    status_line: str | None = None,
    help_lines: list[str] | None = None,
    disabled_reasons: dict[int, str] | None = None,
    disabled_helpers: dict[int, str] | None = None,
) -> int:
    initial_index = state.menu_selection.get(menu_key, 0)
    combined_status = _merge_status_lines(status_line, running_tasks_status(state))
    combined_status = _merge_status_lines(combined_status, last_tool_status_line())
    hint_provider = _menu_hint_provider(menu_key, options)
    menu = Menu(
        stdscr,
        title,
        options,
        initial_index=initial_index,
        command_handler=command_handler,
        command_suggestions=command_suggestions,
        disabled_indices=disabled_indices,
        status_line=combined_status,
        help_lines=help_lines,
        disabled_reasons=disabled_reasons,
        disabled_helpers=disabled_helpers,
        hint_provider=hint_provider,
    )
    choice = menu.navigate()
    if choice >= 0:
        state.menu_selection[menu_key] = choice
    return choice


def root_status_line(state: AppState) -> str | None:
    parts: list[str] = []
    if state.no_foam:
        parts.append("Limited mode: OpenFOAM env not found (simple editor only)")
    running = running_tasks_status(state)
    if running:
        parts.append(running)
    last_tool = last_tool_status_line()
    if last_tool:
        parts.append(last_tool)
    return " | ".join(parts) if parts else None


def has_processor_dirs(case_path: Path) -> bool:
    return any(
        entry.is_dir() and entry.name.startswith("processor")
        for entry in case_path.iterdir()
    )


def _merge_status_lines(base: str | None, extra: str | None) -> str | None:
    if base and extra:
        return f"{base} | {extra}"
    if extra:
        return extra
    return base


def _menu_hint_provider(menu_key: str, options: list[str]) -> Callable[[int], str]:
    def hint(idx: int) -> str:
        if not (0 <= idx < len(options)):
            return ""
        return menu_hint(menu_key, options[idx])

    return hint

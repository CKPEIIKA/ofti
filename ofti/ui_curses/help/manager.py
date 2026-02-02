from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .data import CONTEXT_HELP, MENU_HINTS, TOOL_HELP


@dataclass
class HelpRegistry:
    contexts: dict[str, list[str]] = field(default_factory=lambda: {k: list(v) for k, v in CONTEXT_HELP.items()})
    tool_help: dict[str, list[str]] = field(default_factory=lambda: {k: list(v) for k, v in TOOL_HELP.items()})
    menu_hints: dict[str, dict[str, str]] = field(default_factory=lambda: {k: dict(v) for k, v in MENU_HINTS.items()})

    def register_context(self, name: str, lines: Iterable[str]) -> None:
        self.contexts[name] = list(lines)

    def register_tool(self, tool: str, lines: Iterable[str]) -> None:
        self.tool_help[tool] = list(lines)

    def context(self, name: str) -> list[str]:
        return self.contexts.get(name, [])

    def tool(self, tool: str) -> list[str]:
        return self.tool_help.get(tool, [])

    def menu_hint(self, menu_key: str, label: str) -> str:
        return self.menu_hints.get(menu_key, {}).get(label, "")


help_registry = HelpRegistry()

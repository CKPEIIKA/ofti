"""Framework-neutral CLI command specifications.

A ``CommandSpec`` describes a command's name, summary, positional arguments,
options, and handler without referencing argparse (or any CLI framework). CLI
adapters build their parser from a spec; plugins declare specs instead of
poking argparse internals, so the plugin API stays stable across framework
changes and docs/help/tests can be derived from one definition.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

#: Sentinel for "no default supplied" (None is a valid default).
UNSET: Any = object()


@dataclass(frozen=True)
class ArgumentSpec:
    """A positional argument."""

    name: str
    help: str = ""
    nargs: str | None = None
    type: Callable[[str], Any] | None = None
    default: Any = UNSET


@dataclass(frozen=True)
class OptionSpec:
    """An optional flag/option (one or more flag strings)."""

    flags: tuple[str, ...]
    help: str = ""
    action: str | None = None
    dest: str | None = None
    choices: tuple[str, ...] | None = None
    type: Callable[[str], Any] | None = None
    default: Any = UNSET


@dataclass(frozen=True)
class CommandSpec:
    """A complete command definition, independent of the CLI framework."""

    name: str
    summary: str
    handler: Callable[[Any], int]
    arguments: tuple[ArgumentSpec, ...] = field(default_factory=tuple)
    options: tuple[OptionSpec, ...] = field(default_factory=tuple)

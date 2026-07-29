"""Build argparse subparsers from framework-neutral CommandSpecs.

This is the argparse adapter for ``ofti.core.command_spec``. A future Click or
Typer adapter would build from the same specs; plugins only ever produce specs.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any

from ofti.core.command_spec import UNSET, ArgumentSpec, CommandSpec, OptionSpec
from ofti.plugins import SpecCommandProvider


def _argument_kwargs(arg: ArgumentSpec) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if arg.help:
        kwargs["help"] = arg.help
    if arg.nargs is not None:
        kwargs["nargs"] = arg.nargs
    if arg.type is not None:
        kwargs["type"] = arg.type
    if arg.default is not UNSET:
        kwargs["default"] = arg.default
    return kwargs


def _option_identity_kwargs(opt: OptionSpec) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if opt.help:
        kwargs["help"] = opt.help
    if opt.action is not None:
        kwargs["action"] = opt.action
    if opt.dest is not None:
        kwargs["dest"] = opt.dest
    if opt.choices is not None:
        kwargs["choices"] = list(opt.choices)
    return kwargs


def _option_value_kwargs(opt: OptionSpec) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if opt.type is not None:
        kwargs["type"] = opt.type
    if opt.default is not UNSET:
        kwargs["default"] = opt.default
    if opt.required:
        kwargs["required"] = True
    return kwargs


def _option_kwargs(opt: OptionSpec) -> dict[str, Any]:
    return _option_identity_kwargs(opt) | _option_value_kwargs(opt)


def build_spec_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    spec: CommandSpec,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(spec.name, help=spec.summary)
    for arg in spec.arguments:
        parser.add_argument(arg.name, **_argument_kwargs(arg))
    for opt in spec.options:
        parser.add_argument(*opt.flags, **_option_kwargs(opt))
    parser.set_defaults(func=spec.handler)
    return parser


def build_provider_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    providers: Mapping[str, SpecCommandProvider],
    errors: list[str],
    *,
    surface: str,
) -> None:
    """Build one CLI surface from explicitly registered command providers."""
    for name, provider in sorted(providers.items()):
        try:
            spec = _validated_provider_spec(name, provider)
            build_spec_parser(subparsers, spec)
        except (argparse.ArgumentError, AttributeError, TypeError, ValueError) as exc:
            errors.append(f"{name}: invalid {surface} command: {exc}")


def _validated_provider_spec(
    name: str,
    provider: SpecCommandProvider,
) -> CommandSpec:
    spec = provider.command_spec()
    if spec.name != name:
        raise ValueError(
            f"registered name '{name}' does not match CommandSpec name '{spec.name}'",
        )
    return spec

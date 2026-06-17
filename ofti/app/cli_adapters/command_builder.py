"""Build argparse subparsers from framework-neutral CommandSpecs.

This is the argparse adapter for ``ofti.core.command_spec``. A future Click or
Typer adapter would build from the same specs; plugins only ever produce specs.
"""

from __future__ import annotations

import argparse
from typing import Any

from ofti.core.command_spec import UNSET, ArgumentSpec, CommandSpec, OptionSpec


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


def _option_kwargs(opt: OptionSpec) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if opt.help:
        kwargs["help"] = opt.help
    if opt.action is not None:
        kwargs["action"] = opt.action
    if opt.dest is not None:
        kwargs["dest"] = opt.dest
    if opt.choices is not None:
        kwargs["choices"] = list(opt.choices)
    if opt.type is not None:
        kwargs["type"] = opt.type
    if opt.default is not UNSET:
        kwargs["default"] = opt.default
    if opt.required:
        kwargs["required"] = True
    return kwargs


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

from __future__ import annotations

import argparse

import pytest

from ofti.app.cli_adapters.command_builder import build_spec_parser
from ofti.core.command_spec import ArgumentSpec, CommandSpec, OptionSpec


def _handler(_args: argparse.Namespace) -> int:
    return 0


def test_build_spec_parser_builds_arguments_options_and_handler() -> None:
    spec = CommandSpec(
        name="demo",
        summary="Demo command",
        handler=_handler,
        arguments=(ArgumentSpec("case_dir", help="case"),),
        options=(
            OptionSpec(("--time",), default="latest"),
            OptionSpec(("--json",), action="store_true"),
            OptionSpec(("--mode",), choices=("a", "b"), default="a"),
        ),
    )
    parser = argparse.ArgumentParser()
    build_spec_parser(parser.add_subparsers(), spec)

    args = parser.parse_args(["demo", "/case", "--json", "--mode", "b"])

    assert args.case_dir == "/case"
    assert args.time == "latest"  # option default applied
    assert args.json is True  # store_true
    assert args.mode == "b"
    assert args.func is _handler  # handler wired via set_defaults


def test_build_spec_parser_enforces_choices() -> None:
    spec = CommandSpec(
        name="demo",
        summary="d",
        handler=_handler,
        options=(OptionSpec(("--mode",), choices=("a", "b")),),
    )
    parser = argparse.ArgumentParser()
    build_spec_parser(parser.add_subparsers(), spec)

    with pytest.raises(SystemExit):
        parser.parse_args(["demo", "--mode", "z"])


def test_build_spec_parser_enforces_required_option() -> None:
    spec = CommandSpec(
        name="demo",
        summary="d",
        handler=_handler,
        options=(OptionSpec(("--patch",), required=True),),
    )
    parser = argparse.ArgumentParser()
    build_spec_parser(parser.add_subparsers(), spec)

    with pytest.raises(SystemExit):
        parser.parse_args(["demo"])  # missing required --patch

    args = parser.parse_args(["demo", "--patch", "wall"])
    assert args.patch == "wall"

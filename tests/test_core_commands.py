from ofti.core.commands import CommandKind, is_blocked_in_no_foam, parse_command


def test_parse_command_strips_colon_and_empty() -> None:
    assert parse_command(":") is None
    assert parse_command(":   ") is None


def test_parse_command_recognizes_simple_actions() -> None:
    action = parse_command(":quit")
    assert action is not None
    assert action.kind == CommandKind.QUIT
    action = parse_command(":check")
    assert action is not None
    assert action.kind == CommandKind.CHECK
    action = parse_command(":tools")
    assert action is not None
    assert action.kind == CommandKind.TOOLS
    action = parse_command(":diag")
    assert action is not None
    assert action.kind == CommandKind.DIAGNOSTICS
    action = parse_command(":search")
    assert action is not None
    assert action.kind == CommandKind.SEARCH
    action = parse_command(":foamenv")
    assert action is not None
    assert action.kind == CommandKind.FOAM_ENV


def test_parse_command_run_tool_and_tool_alias() -> None:
    action = parse_command(":run simpleFoam")
    assert action is not None
    assert action.kind == CommandKind.RUN_TOOL
    assert action.args == ("simpleFoam",)

    action = parse_command("simpleFoam", tool_names=["simpleFoam"])
    assert action is not None
    assert action.kind == CommandKind.RUN_TOOL
    assert action.args == ("simpleFoam",)


def test_parse_command_cancel_requires_name() -> None:
    action = parse_command(":cancel")
    assert action is not None
    assert action.kind == CommandKind.CANCEL
    assert action.error is not None


def test_blocked_in_no_foam() -> None:
    check_action = parse_command(":check")
    assert check_action is not None
    assert is_blocked_in_no_foam(check_action)
    run_action = parse_command(":run")
    assert run_action is not None
    assert is_blocked_in_no_foam(run_action)
    help_action = parse_command(":help")
    assert help_action is not None
    assert not is_blocked_in_no_foam(help_action)

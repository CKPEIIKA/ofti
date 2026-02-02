from ofti.core.commands import CommandKind, parse_command


def test_tool_command_background_flag() -> None:
    action = parse_command(":tool blockMesh -b", tool_names=["blockMesh"])
    assert action.kind == CommandKind.RUN_TOOL
    assert action.background
    assert action.args == ("blockMesh",)


def test_direct_tool_background_flag() -> None:
    action = parse_command("blockMesh -b", tool_names=["blockMesh"])
    assert action.kind == CommandKind.RUN_TOOL
    assert action.background
    assert action.args == ("blockMesh",)

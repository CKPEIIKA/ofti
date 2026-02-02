from ofti.ui_curses.help.manager import HelpRegistry, help_registry


def test_help_registry_defaults() -> None:
    registry = HelpRegistry()
    assert registry.context("main")
    assert registry.tool("renumbermesh")


def test_help_registry_registers_new_entries() -> None:
    registry = HelpRegistry()
    registry.register_context("custom", ["line"])
    registry.register_tool("testtool", ["do this"])
    assert registry.context("custom") == ["line"]
    assert registry.tool("testtool") == ["do this"]


def test_global_registry_changes() -> None:
    help_registry.register_context("test", ["ok"])
    help_registry.register_tool("test", ["run"])
    assert help_registry.context("test") == ["ok"]
    assert help_registry.tool("test") == ["run"]

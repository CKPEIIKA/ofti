from unittest import mock

from ofti.app import cli


def test_cli_main_invokes_run_tui_with_defaults(tmp_path, monkeypatch) -> None:
    target = tmp_path / "case"
    target.mkdir()

    monkeypatch.chdir(target)
    monkeypatch.setattr(cli, "_has_interactive_terminal", lambda: True)

    with mock.patch("ofti.app.cli.run_tui") as run:
        code = cli.main([])

    assert code == 0
    run.assert_called_once_with(str(target), debug=False)


def test_cli_main_delegates_tool_subcommand(monkeypatch) -> None:
    with mock.patch("ofti.app.cli.cli_tools_main", return_value=7) as tool_main:
        code = cli.main(["knife", "status"])

    assert code == 7
    tool_main.assert_called_once_with(["knife", "status"])


def test_cli_main_delegates_bundle_subcommands() -> None:
    with mock.patch("ofti.app.cli.cli_tools_main", return_value=0) as tool_main:
        code = cli.main(["bundle", "case", "CASE", "--output", "case.ofti.tar.gz"])

    assert code == 0
    tool_main.assert_called_once_with(["bundle", "case", "CASE", "--output", "case.ofti.tar.gz"])


def test_cli_main_delegates_bundle_set_subcommand() -> None:
    with mock.patch("ofti.app.cli.cli_tools_main", return_value=0) as tool_main:
        code = cli.main(["bundle", "set", "CASE_A", "CASE_B", "--output", "study.tar.gz"])

    assert code == 0
    tool_main.assert_called_once_with(["bundle", "set", "CASE_A", "CASE_B", "--output", "study.tar.gz"])


def test_cli_main_delegates_result_subcommand() -> None:
    with mock.patch("ofti.app.cli.cli_tools_main", return_value=0) as tool_main:
        code = cli.main(["result"])

    assert code == 0
    tool_main.assert_called_once_with(["result"])


def test_cli_main_rejects_headless_tui_without_traceback(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "_has_interactive_terminal", lambda: False)

    code = cli.main(["CASE"])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "interactive TUI requires a terminal" in captured.err


def test_cli_plain_never_starts_tui(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "_has_interactive_terminal", lambda: True)
    with mock.patch("ofti.app.cli.run_tui") as run:
        code = cli.main(["--plain", "CASE"])

    assert code == 2
    assert "--plain/--no-tty requires a non-interactive command" in capsys.readouterr().err
    run.assert_not_called()


def test_cli_plain_is_removed_before_tool_dispatch() -> None:
    with mock.patch("ofti.app.cli.cli_tools_main", return_value=0) as tool_main:
        code = cli.main(["--plain", "knife", "status", "CASE", "--json"])

    assert code == 0
    tool_main.assert_called_once_with(["knife", "status", "CASE", "--json"])


def test_cli_main_delegates_version_flag() -> None:
    with mock.patch("ofti.app.cli.cli_tools_main", return_value=0) as tool_main:
        code = cli.main(["--version"])

    assert code == 0
    tool_main.assert_called_once_with(["--version"])


def test_cli_main_delegates_version_subcommand() -> None:
    with mock.patch("ofti.app.cli.cli_tools_main", return_value=0) as tool_main:
        code = cli.main(["version"])

    assert code == 0
    tool_main.assert_called_once_with(["version"])


def test_cli_help_mentions_version_and_noninteractive_tools() -> None:
    help_text = cli.build_parser().format_help()
    assert "--version" in help_text
    assert "knife|plot|watch|run|bundle|result|plugins|version" in help_text
    assert "Examples:" in help_text

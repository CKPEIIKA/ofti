from unittest import mock

from ofti.app import cli


def test_cli_main_invokes_run_tui_with_defaults(tmp_path, monkeypatch) -> None:
    target = tmp_path / "case"
    target.mkdir()

    monkeypatch.chdir(target)

    with mock.patch("ofti.app.cli.run_tui") as run:
        cli.main([])

    run.assert_called_once_with(str(target), debug=False)

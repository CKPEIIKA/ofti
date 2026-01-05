from unittest import mock

import runpy
import sys


def test_cli_main_invokes_run_tui_with_defaults(tmp_path) -> None:
    target = tmp_path / "case"
    target.mkdir()

    with mock.patch("tui.app.run_tui") as run:
        # Simulate running `of_tui` with no extra args.
        argv_orig = sys.argv
        sys.argv = ["of_tui"]
        try:
            runpy.run_path("of_tui", run_name="__main__")
        finally:
            sys.argv = argv_orig

    run.assert_called_once()

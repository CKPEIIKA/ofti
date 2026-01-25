from pathlib import Path
from unittest import mock

from ofti.app.app import run_tui


def test_run_tui_resolves_case_dir(tmp_path: Path) -> None:
    """
    Ensure that run_tui resolves the case directory so that
    later Path.relative_to calls do not fail when the user
    passes a relative path (e.g. 'of_example').
    """
    case_dir = tmp_path / "case"
    case_dir.mkdir()

    with mock.patch("ofti.app.app.curses.wrapper") as wrapper:
        run_tui(str(case_dir.relative_to(tmp_path)))

    # Second argument passed into curses.wrapper should be absolute
    assert wrapper.call_count == 1
    _, args, _ = wrapper.mock_calls[0]
    resolved_path = args[1]
    assert isinstance(resolved_path, Path)
    assert resolved_path.is_absolute()

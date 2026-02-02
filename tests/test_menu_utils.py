from pathlib import Path

from ofti.app.menu_utils import has_processor_dirs


def test_has_processor_dirs(tmp_path: Path) -> None:
    case = tmp_path / "case"
    proc_dir = case / "processor0"
    proc_dir.mkdir(parents=True)
    assert has_processor_dirs(case)


def test_has_processor_dirs_missing(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    assert not has_processor_dirs(case)

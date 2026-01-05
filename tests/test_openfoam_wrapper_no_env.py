from pathlib import Path
from unittest import mock

import pytest

from tui.openfoam import (
    OpenFOAMError,
    ensure_environment,
    get_entry_comments,
    list_keywords,
    list_subkeys,
    read_entry,
    verify_case,
)


def test_ensure_environment_raises_when_missing() -> None:
    with mock.patch("tui.openfoam.shutil.which", return_value=None):
        with pytest.raises(OpenFOAMError):
            ensure_environment()


def test_list_keywords_parses_output(tmp_path: Path) -> None:
    fake_file = tmp_path / "dict"
    fake_file.write_text("dummy;")

    completed = mock.Mock()
    completed.returncode = 0
    completed.stdout = "a\nb\n\n"
    with mock.patch("tui.openfoam.run_foam_dictionary", return_value=completed):
        result = list_keywords(fake_file)
        assert result == ["a", "b"]


def test_list_subkeys_handles_dictionary_entry(tmp_path: Path) -> None:
    fake_file = tmp_path / "dict"
    fake_file.write_text("dummy;")

    completed = mock.Mock()
    completed.returncode = 0
    completed.stdout = "subA\nsubB\n"
    with mock.patch("tui.openfoam.run_foam_dictionary", return_value=completed):
        result = list_subkeys(fake_file, "parent")
        assert result == ["subA", "subB"]


def test_list_subkeys_non_dict_returns_empty(tmp_path: Path) -> None:
    fake_file = tmp_path / "dict"
    fake_file.write_text("dummy;")

    completed = mock.Mock()
    completed.returncode = 1
    completed.stderr = "not a dictionary"
    with mock.patch("tui.openfoam.run_foam_dictionary", return_value=completed):
        result = list_subkeys(fake_file, "parent")
        assert result == []


def test_get_entry_comments_picks_preceding_comment_block(tmp_path: Path) -> None:
    case_file = tmp_path / "dict"
    case_file.write_text(
        "// comment 1\n"
        "// comment 2\n"
        "entry1 10;\n"
        "\n"
        "// other\n"
        "entry2 20;\n"
    )

    comments = get_entry_comments(case_file, "entry1")
    assert "comment 1" in comments[0]
    assert "comment 2" in comments[1]


def test_read_entry_error(tmp_path: Path) -> None:
    fake_file = tmp_path / "dict"
    fake_file.write_text("dummy;")

    completed = mock.Mock()
    completed.returncode = 1
    completed.stderr = "bad"
    with mock.patch("tui.openfoam.run_foam_dictionary", return_value=completed):
        with pytest.raises(OpenFOAMError):
            read_entry(fake_file, "key")


def test_read_entry_strips_leading_key_for_scalar(tmp_path: Path) -> None:
    fake_file = tmp_path / "dict"
    fake_file.write_text("dummy;")

    completed = mock.Mock()
    completed.returncode = 0
    completed.stdout = "preMij 0.014;\n"
    with mock.patch("tui.openfoam.run_foam_dictionary", return_value=completed):
        value = read_entry(fake_file, "preMij")

    assert value == "0.014;"


def test_verify_case_collects_errors(tmp_path: Path) -> None:
    case = tmp_path / "case"
    system = case / "system"
    system.mkdir(parents=True)
    f_ok = system / "ok"
    f_bad = system / "bad"
    f_ok.write_text("ok;")
    f_bad.write_text("bad;")

    def fake_run(file_path: Path, args):
        completed = mock.Mock()
        if file_path == f_ok:
            completed.returncode = 0
            completed.stderr = ""
            completed.stdout = "key\n"
        else:
            completed.returncode = 1
            completed.stderr = "parse error"
            completed.stdout = ""
        return completed

    with mock.patch("tui.openfoam.run_foam_dictionary", side_effect=fake_run):
        results = verify_case(case)

    assert f_ok in results and results[f_ok] is None
    assert f_bad in results and "parse error" in results[f_bad]

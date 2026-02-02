from pathlib import Path
from unittest import mock

import pytest

from ofti.foam.openfoam import (
    OpenFOAMError,
    get_entry_comments,
    list_keywords,
    list_subkeys,
    missing_required_entries,
    normalize_scalar_token,
    parse_required_entries,
    read_entry,
    verify_case,
)
from ofti.foam.openfoam_env import ensure_environment


def _write_foamfile(path: Path) -> None:
    path.write_text(
        "FoamFile\n"
        "{\n"
        "    version 2.0;\n"
        "}\n",
    )


def test_ensure_environment_raises_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("WM_PROJECT_DIR", raising=False)
    monkeypatch.delenv("WM_PROJECT_VERSION", raising=False)
    monkeypatch.delenv("FOAM_VERSION", raising=False)
    with (
        mock.patch("ofti.foam.openfoam_env.shutil.which", return_value=None),
        pytest.raises(OpenFOAMError),
    ):
        ensure_environment()


def test_list_keywords_parses_output(tmp_path: Path) -> None:
    fake_file = tmp_path / "dict"
    _write_foamfile(fake_file)

    with mock.patch(
        "ofti.foam.openfoam.foamlib_integration.list_keywords",
        return_value=["a", "b"],
    ):
        result = list_keywords(fake_file)
        assert result == ["a", "b"]


def test_list_subkeys_handles_dictionary_entry(tmp_path: Path) -> None:
    fake_file = tmp_path / "dict"
    _write_foamfile(fake_file)

    with mock.patch(
        "ofti.foam.openfoam.foamlib_integration.list_subkeys",
        return_value=["subA", "subB"],
    ):
        result = list_subkeys(fake_file, "parent")
        assert result == ["subA", "subB"]


def test_list_subkeys_non_dict_returns_empty(tmp_path: Path) -> None:
    fake_file = tmp_path / "dict"
    _write_foamfile(fake_file)

    with mock.patch(
        "ofti.foam.openfoam.foamlib_integration.list_subkeys",
        side_effect=ValueError("not a dict"),
    ):
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
        "entry2 20;\n",
    )

    comments = get_entry_comments(case_file, "entry1")
    assert "comment 1" in comments[0]
    assert "comment 2" in comments[1]


def test_read_entry_error(tmp_path: Path) -> None:
    fake_file = tmp_path / "dict"
    _write_foamfile(fake_file)

    with (
        mock.patch(
            "ofti.foam.openfoam.foamlib_integration.read_entry",
            side_effect=KeyError("bad"),
        ),
        pytest.raises(OpenFOAMError),
    ):
        read_entry(fake_file, "key")


def test_read_entry_strips_leading_key_for_scalar(tmp_path: Path) -> None:
    fake_file = tmp_path / "dict"
    _write_foamfile(fake_file)

    with mock.patch(
        "ofti.foam.openfoam.foamlib_integration.read_entry",
        return_value="0.014;",
    ):
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

    def fake_list_keywords(file_path: Path) -> list[str]:
        if file_path == f_bad:
            raise OpenFOAMError("parse error")
        return []

    with mock.patch.multiple(
        "ofti.foam.openfoam",
        list_keywords=mock.Mock(side_effect=fake_list_keywords),
        list_subkeys=mock.Mock(return_value=[]),
        get_entry_info=mock.Mock(return_value=[]),
        get_entry_enum_values=mock.Mock(return_value=[]),
        read_entry=mock.Mock(return_value="value;"),
    ):
        results = verify_case(case)

    assert f_ok in results and not results[f_ok].errors
    assert f_bad in results and "parse error" in results[f_bad].errors[0]


def test_verify_case_detects_missing_required_entries(tmp_path: Path) -> None:
    case = tmp_path / "case"
    system = case / "system"
    system.mkdir(parents=True)
    control = system / "controlDict"
    control.write_text("application simpleFoam;")

    def fake_list_keywords(_file_path: Path) -> list[str]:
        return ["application"]

    def fake_list_subkeys(_file_path: Path, entry: str) -> list[str]:
        return ["type"] if entry == "application" else []

    def fake_get_entry_info(_file_path: Path, entry: str) -> list[str]:
        if entry == "application":
            return ["Required entries:", "- type", "- value"]
        return []

    with mock.patch.multiple(
        "ofti.foam.openfoam",
        list_keywords=mock.Mock(side_effect=fake_list_keywords),
        list_subkeys=mock.Mock(side_effect=fake_list_subkeys),
        get_entry_info=mock.Mock(side_effect=fake_get_entry_info),
        get_entry_enum_values=mock.Mock(return_value=[]),
        read_entry=mock.Mock(return_value="simpleFoam;"),
    ):
        results = verify_case(case)

    issues = results[control].errors
    assert any("missing required entries" in issue for issue in issues)


def test_verify_case_detects_invalid_enum_value(tmp_path: Path) -> None:
    case = tmp_path / "case"
    system = case / "system"
    system.mkdir(parents=True)
    control = system / "controlDict"
    control.write_text("application simpleFoam;")

    def fake_list_keywords(_file_path: Path) -> list[str]:
        return ["application"]

    with mock.patch.multiple(
        "ofti.foam.openfoam",
        list_keywords=mock.Mock(side_effect=fake_list_keywords),
        list_subkeys=mock.Mock(return_value=[]),
        get_entry_info=mock.Mock(return_value=[]),
        get_entry_enum_values=mock.Mock(return_value=["simpleFoam", "pisoFoam"]),
        read_entry=mock.Mock(return_value="application potentialFoam;"),
    ):
        results = verify_case(case)

    issues = results[control].errors
    assert any("invalid value" in issue for issue in issues)


def test_parse_required_entries_handles_inline_and_block() -> None:
    lines = [
        "Required entries: type value",
        "Required entries:",
        "- alpha",
        "- beta",
        "",
        "Optional entries: foo",
    ]
    assert parse_required_entries(lines) == ["type", "value", "alpha", "beta"]


def test_missing_required_entries_reports_missing() -> None:
    missing = missing_required_entries(["type", "value"], ["type"])
    assert missing == ["value"]


def test_normalize_scalar_token_extracts_final_token() -> None:
    value = normalize_scalar_token("application potentialFoam;  ")
    assert value == "potentialFoam"


def test_verify_case_calls_progress_callback(tmp_path: Path) -> None:
    case = tmp_path / "case"
    system = case / "system"
    system.mkdir(parents=True)
    control = system / "controlDict"
    control.write_text("application simpleFoam;")

    called: list[Path] = []

    def fake_list_keywords(_file_path: Path) -> list[str]:
        return []

    def progress(path: Path) -> None:
        called.append(path)

    with mock.patch.multiple(
        "ofti.foam.openfoam",
        list_keywords=mock.Mock(side_effect=fake_list_keywords),
        list_subkeys=mock.Mock(return_value=[]),
        get_entry_info=mock.Mock(return_value=[]),
        get_entry_enum_values=mock.Mock(return_value=[]),
        read_entry=mock.Mock(return_value="value;"),
    ):
        verify_case(case, progress=progress)

    assert called == [control]

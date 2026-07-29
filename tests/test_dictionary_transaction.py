import json
from pathlib import Path

from ofti.tools import dictionary_transaction_service as service


def _case(tmp_path: Path) -> Path:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text(
        "FoamFile\n{\nversion 2.0;\nformat ascii;\nclass dictionary;\n"
        "object controlDict;\n}\napplication simpleFoam;\nendTime 10;\nwriteInterval 1;\n",
    )
    return case


def test_transaction_previews_then_applies_multiple_entries(tmp_path: Path) -> None:
    case = _case(tmp_path)
    edits = [
        ("system/controlDict", "endTime", "20"),
        ("system/controlDict", "writeInterval", "2"),
    ]

    preview = service.set_entries_payload(case, edits, apply=False)
    applied = service.set_entries_payload(case, edits)

    assert preview["applied"] is False
    assert preview["snapshot"] is None
    assert applied["ok"] is True, applied
    assert applied["applied"] is True
    assert applied["atomic"] is True
    assert Path(applied["snapshot"]).joinpath("snapshot.json").is_file()
    manifest = Path(applied["manifest"])
    assert manifest.is_file()
    assert json.loads(manifest.read_text())["format"] == "ofti.dictionary-transaction"
    assert "system/controlDict.before" in preview["diff"]
    assert "-endTime 10;" in preview["diff"]
    assert "+endTime 20;" in preview["diff"]
    text = (case / "system" / "controlDict").read_text()
    assert "endTime 20;" in text
    assert "writeInterval 2;" in text


def test_transaction_rolls_back_every_file_when_an_edit_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    case = _case(tmp_path)
    control = case / "system" / "controlDict"
    solution = case / "system" / "fvSolution"
    solution.write_text(
        "FoamFile\n{\nclass dictionary;\nobject fvSolution;\n}\nsolver smoothSolver;\n",
        encoding="utf-8",
    )
    originals = {path: path.read_bytes() for path in (control, solution)}
    calls = 0
    replace = service._replace_staged_file

    def fail_second_replace(staged: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("replace failed")
        replace(staged, destination)

    monkeypatch.setattr(service, "_replace_staged_file", fail_second_replace)

    payload = service.set_entries_payload(
        case,
        [
            ("system/controlDict", "endTime", "20"),
            ("system/fvSolution", "solver", "GAMG"),
        ],
    )

    assert payload["ok"] is False
    assert payload["rolled_back"] is True
    assert payload["manifest"] is not None
    assert all(path.read_bytes() == original for path, original in originals.items())


def test_parse_edit_specs_rejects_ambiguous_input() -> None:
    assert service.parse_edit_specs(["system/controlDict:endTime=20"]) == [
        ("system/controlDict", "endTime", "20"),
    ]


def test_transaction_rejects_missing_key_without_mutation(tmp_path: Path) -> None:
    case = _case(tmp_path)
    control_dict = case / "system" / "controlDict"
    before = control_dict.read_bytes()

    try:
        service.set_entries_payload(
            case,
            [("system/controlDict", "missing.nested.key", "value")],
        )
    except ValueError as exc:
        assert "use --insert" in str(exc)
    else:
        raise AssertionError("missing key should require explicit insertion")

    assert control_dict.read_bytes() == before


def test_transaction_reports_insert_and_normalized_update_values(
    tmp_path: Path,
    monkeypatch,
) -> None:
    case = _case(tmp_path)
    values = {"endTime": "10;", "newKey": None}
    monkeypatch.setattr(
        service, "read_entry", lambda _path, key: values[key] if values[key] is not None else _missing()
    )
    payload = service.set_entries_payload(
        case,
        [
            ("system/controlDict", "endTime", "20;"),
            ("system/controlDict", "newKey", "newValue;"),
        ],
        allow_insert=True,
    )

    assert payload["edits"][0] == {
        "file": "system/controlDict",
        "key": "endTime",
        "before": "10",
        "after": "20",
        "existed": True,
        "operation": "update",
    }
    assert payload["edits"][1]["operation"] == "insert"
    assert payload["edits"][1]["before"] is None


def test_transaction_preserves_unrelated_precision_and_requested_literal(tmp_path: Path) -> None:
    case = _case(tmp_path)
    control = case / "system" / "controlDict"
    control.write_text(
        control.read_text(encoding="utf-8") + "rhoInf 0.006666666670001;\n" + "probePoint (-0.0152362205001 0 0);\n",
        encoding="utf-8",
    )

    payload = service.set_entries_payload(
        case,
        [("system/controlDict", "endTime", "5e-05")],
    )

    text = control.read_text(encoding="utf-8")
    assert payload["ok"] is True
    assert "endTime 5e-05;" in text
    assert "rhoInf 0.006666666670001;" in text
    assert "probePoint (-0.0152362205001 0 0);" in text
    assert "+endTime 5e-05;" in payload["diff"]


def _missing() -> str:
    raise KeyError("missing")

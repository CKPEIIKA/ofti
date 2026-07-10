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
    assert Path(applied["snapshot"]).joinpath("snapshot.json").is_file()
    text = (case / "system" / "controlDict").read_text()
    assert "endTime 20.0;" in text
    assert "writeInterval 2.0;" in text


def test_transaction_rolls_back_every_file_when_an_edit_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    case = _case(tmp_path)
    original = (case / "system" / "controlDict").read_bytes()
    calls = 0

    def _write(path: Path, key: str, value: str) -> bool:
        nonlocal calls
        calls += 1
        path.write_text(f"changed {key} {value}\n")
        return calls == 1

    monkeypatch.setattr(service, "write_entry", _write)

    payload = service.set_entries_payload(
        case,
        [
            ("system/controlDict", "endTime", "20"),
            ("system/controlDict", "writeInterval", "2"),
        ],
    )

    assert payload["ok"] is False
    assert payload["rolled_back"] is True
    assert (case / "system" / "controlDict").read_bytes() == original


def test_parse_edit_specs_rejects_ambiguous_input() -> None:
    assert service.parse_edit_specs(["system/controlDict:endTime=20"]) == [
        ("system/controlDict", "endTime", "20"),
    ]

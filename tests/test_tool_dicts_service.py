from pathlib import Path

from ofti.core import tool_dicts_service


def test_apply_edit_plan_collects_failures(monkeypatch) -> None:
    calls: list[tuple[Path, list[str], str]] = []

    def fake_apply(_case, file_path, key_path, value):
        calls.append((file_path, key_path, value))
        return value != "bad"

    monkeypatch.setattr(tool_dicts_service, "apply_assignment_or_write", fake_apply)

    edits = [
        (Path("system/controlDict"), ["application"], "simpleFoam"),
        (Path("system/controlDict"), ["startFrom"], "bad"),
    ]
    failures = tool_dicts_service.apply_edit_plan(Path("/case"), edits)
    assert len(calls) == 2
    assert failures == [(Path("system/controlDict"), ["startFrom"], "bad")]

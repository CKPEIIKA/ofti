from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ofti.tools import change_queue_service


def test_change_queue_payload_reports_case_dict_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("application simpleFoam;\n")

    monkeypatch.setattr(
        change_queue_service,
        "run_trusted",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=" M system/controlDict\n?? 0/U\n",
            stderr="",
        ),
    )

    payload = change_queue_service.change_queue_payload(case)

    assert payload["source"] == "git"
    assert payload["count"] == 2
    assert payload["changes"][0]["path"] == "system/controlDict"
    assert payload["diff"]
    assert payload["actions"][1]["action"] == "snapshot"
    assert payload["actions"][2]["status"] == "blocked"


def test_change_queue_payload_can_write_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "constant" / "polyMesh").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("application simpleFoam;\n")

    monkeypatch.setattr(
        change_queue_service,
        "run_trusted",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=" M system/controlDict\n",
            stderr="",
        ),
    )

    payload = change_queue_service.change_queue_payload(case, write_snapshot=True)

    assert payload["snapshot_path"]
    assert Path(str(payload["snapshot_path"])).is_file()
    assert payload["actions"][1]["status"] == "done"
    assert payload["actions"][2]["status"] == "ready"

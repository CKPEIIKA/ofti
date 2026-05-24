from __future__ import annotations

from pathlib import Path

from ofti.tools.flight_deck_service import flight_deck_payload
from ofti.tools.launch_checklist_service import launch_checklist_payload
from ofti.tools.monitor_builder_service import monitor_builder_payload
from ofti.tools.numerics_service import numerics_payload


def _case(path: Path) -> Path:
    case = path / "case"
    (case / "system").mkdir(parents=True)
    (case / "constant" / "polyMesh").mkdir(parents=True)
    (case / "system" / "controlDict").write_text(
        "application simpleFoam;\nendTime 10;\ndeltaT 1;\nwriteInterval 1;\nfunctions {}\n",
    )
    (case / "system" / "fvSchemes").write_text("ddtSchemes {}\ndivSchemes {}\n")
    (case / "system" / "fvSolution").write_text("solvers {}\nSIMPLE {}\n")
    return case


def test_numerics_payload_summarizes_core_dictionaries(tmp_path: Path) -> None:
    payload = numerics_payload(_case(tmp_path))
    text = "\n".join(str(row) for row in payload["files"] + payload["controls"] + payload["schemes"])

    assert payload["case"].endswith("case")
    assert "system/fvSchemes" in text
    assert "endTime" in text
    assert payload["diff_before_write"] is True
    assert payload["convergence_contract"][0]["source"] == "system/fvSolution"
    assert payload["presets"][0]["name"] == "conservative steady RANS"
    assert payload["presets"][0]["diff"][0].startswith("--- current numerics")


def test_launch_checklist_payload_reports_ready_rows(tmp_path: Path) -> None:
    payload = launch_checklist_payload(_case(tmp_path))

    assert payload["ready"] is True
    assert payload["gate"] == "GO"
    assert payload["actions"][0]["action"] == "launch"
    assert payload["log_strategy"]["rotate_before_launch"] is False
    assert any(row["item"] == "Mesh" and row["status"] == "pass" for row in payload["rows"])


def test_launch_checklist_payload_blocks_and_points_to_failing_items(tmp_path: Path) -> None:
    case = _case(tmp_path)
    (case / "constant" / "polyMesh").rmdir()

    payload = launch_checklist_payload(case)

    assert payload["ready"] is False
    assert payload["gate"] == "NO-GO"
    assert any(row["item"] == "Mesh" for row in payload["blocking"])
    assert payload["actions"][0]["action"] == "open failing item"
    assert payload["actions"][0]["target"] == "constant/polyMesh"


def test_flight_deck_payload_degrades_without_running_solver(tmp_path: Path) -> None:
    payload = flight_deck_payload(_case(tmp_path))

    assert payload["case"].endswith("case")
    assert payload["actions"]
    assert "status" in payload
    assert payload["control"]["values"]["deltaT"] == "1"
    assert payload["runtime_queue"][0]["key"] == "safe-stop"
    assert payload["runtime_queue"][0]["diff"][0].startswith("--- current")
    assert payload["runtime_queue"][0]["edit_service"] == "control_dict_edit_payload"
    assert payload["runtime_queue"][0]["snapshot_required"] is True
    assert any(row["key"] == "deltaT" and row["status"] == "idle" for row in payload["runtime_queue"])


def test_monitor_builder_plans_and_writes_function_object_include(tmp_path: Path) -> None:
    case = _case(tmp_path)

    planned = monitor_builder_payload(case, include_diff=True)
    assert planned["changed"] is True
    assert planned["written"] is False
    assert "residuals" in "\n".join(planned["diff"])

    written = monitor_builder_payload(case, monitors=["residuals", "courant"], write=True)
    target = case / "system" / "controlDict.functions"
    assert written["written"] is True
    assert target.is_file()
    text = target.read_text(encoding="utf-8")
    assert "type            residuals;" in text
    assert "type            CourantNo;" in text

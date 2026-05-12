from __future__ import annotations

from pathlib import Path

from ofti.tools.mesh_radar_service import mesh_radar_payload


def test_mesh_radar_payload_parses_checkmesh_log(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    (case / "log.checkMesh").write_text(
        "\n".join(
            [
                "Number of cells: 1,000",
                "Number of faces: 2,000",
                "Number of points: 3,000",
                "Max non-orthogonality = 72",
                "Max skewness = 2.1",
                "Max aspect ratio = 120",
                "Failed 1 mesh checks",
            ],
        ),
    )

    payload = mesh_radar_payload(case)

    assert payload["status"] == "fail"
    text = "\n".join(str(row) for row in payload["metrics"])
    assert "1000" in text
    assert "Max non-orth" in text
    assert "warn" in text
    assert payload["notes"] == ["Failed checks: 1"]


def test_mesh_radar_payload_without_log_reports_missing_or_mesh(tmp_path: Path) -> None:
    case = tmp_path / "case"
    mesh = case / "constant" / "polyMesh"
    mesh.mkdir(parents=True)
    (mesh / "boundary").write_text("boundary")

    payload = mesh_radar_payload(case)

    assert payload["status"] == "mesh"
    assert payload["notes"] == ["No checkMesh log found."]

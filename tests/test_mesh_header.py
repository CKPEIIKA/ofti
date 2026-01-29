"""Mesh header stats parsing."""

from pathlib import Path

from ofti.core.case import detect_mesh_stats


def test_detect_mesh_stats_from_checkmesh_log() -> None:
    case_path = Path("examples/pitzDaily")
    stats = detect_mesh_stats(case_path)
    assert "12225 cells" in stats
    assert "skew=0.26" in stats

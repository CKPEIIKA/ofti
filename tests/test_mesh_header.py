"""Mesh header stats parsing."""

from pathlib import Path

from ofti.core.case import detect_mesh_stats


def test_detect_mesh_stats_from_checkmesh_log() -> None:
    case_path = Path("examples/of_example")
    stats = detect_mesh_stats(case_path)
    assert "mesh" in stats or "cells" in stats

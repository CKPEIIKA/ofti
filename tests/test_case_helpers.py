from pathlib import Path

from ofti.core.case import (
    detect_mesh_stats,
    has_mesh,
    latest_checkmesh_log,
    parse_cells_count,
    parse_max_skewness,
)


def test_parse_cells_and_skew() -> None:
    text = "Number of cells: 1000\nMax skewness = 2.5\n"
    assert parse_cells_count(text) == "1000"
    assert parse_max_skewness(text) == "2.5"


def test_detect_mesh_stats_from_log(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    log = case_dir / "log.checkMesh"
    log.parent.mkdir(parents=True)
    log.write_text("Number of cells: 10\nMax skewness = 1.2\n")
    # ensure mesh exists
    boundary = case_dir / "constant" / "polyMesh" / "boundary"
    boundary.parent.mkdir(parents=True)
    boundary.write_text("boundary data")

    assert latest_checkmesh_log(case_dir) == log
    assert has_mesh(case_dir) is True
    summary = detect_mesh_stats(case_dir)
    assert "10 cells" in summary
    assert "skew=1.2" in summary

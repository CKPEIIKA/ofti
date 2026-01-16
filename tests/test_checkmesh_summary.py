"""checkMesh summary parsing."""

from of_tui.tools import _format_checkmesh_summary


def test_checkmesh_summary_parses_values() -> None:
    output = "\n".join(
        [
            "Checking geometry...",
            "    Number of cells: 12345",
            "    Max non-orthogonality = 62",
            "    Max skewness = 2.1",
            "Mesh OK.",
        ]
    )
    summary = _format_checkmesh_summary(output)
    assert "Cells" in summary
    assert "12345" in summary
    assert "non-orth" in summary
    assert "62" in summary
    assert "skewness" in summary
    assert "2.1" in summary
    assert "Status" in summary
    assert "OK" in summary


def test_checkmesh_summary_table_has_borders() -> None:
    output = "Number of cells: 10\\nMax skewness = 1.0\\nMesh OK."
    summary = _format_checkmesh_summary(output)
    lines = summary.splitlines()
    assert lines[0].startswith("+")
    assert lines[0].endswith("+")
    assert any("| Cells" in line for line in lines)

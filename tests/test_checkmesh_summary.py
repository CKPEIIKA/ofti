"""checkMesh summary parsing."""

from ofti.core.checkmesh import format_checkmesh_summary


def test_checkmesh_summary_parses_values() -> None:
    output = "\n".join(
        [
            "Checking geometry...",
            "    Number of cells: 12345",
            "    Max non-orthogonality = 62",
            "    Max skewness = 2.1",
            "Mesh OK.",
        ],
    )
    summary = format_checkmesh_summary(output)
    assert "CHECKMESH SUMMARY" in summary
    assert "Counts:" in summary
    assert "Quality:" in summary
    assert "12345" in summary
    assert "non-orth" in summary
    assert "62" in summary
    assert "skewness" in summary
    assert "2.1" in summary
    assert "OK" in summary


def test_checkmesh_summary_includes_notes() -> None:
    output = "Number of cells: 10\\nMax skewness = 1.0\\nMesh OK."
    summary = format_checkmesh_summary(output)
    assert "Notes:" in summary
    assert "Status: OK" in summary
    assert "Errors: 0" in summary


def test_checkmesh_summary_uses_stderr_content() -> None:
    output = "stderr: Number of cells: 42\\nMax non-orthogonality = 5\\nMesh OK."
    summary = format_checkmesh_summary(output)
    assert "42" in summary
    assert "5" in summary

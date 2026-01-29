from ofti.ui_curses import layout


def test_format_banner_row_truncates() -> None:
    row = layout.format_banner_row("left" * 20, "right" * 20, column_width=10)
    assert row.startswith("| ")
    assert "| " in row


def test_foam_style_banner_has_frame() -> None:
    rows = [("Left", "Right"), ("Second", "Line")]
    banner = layout.foam_style_banner("ofti", rows)
    assert banner[0].startswith("/*")
    assert banner[-1].endswith("*/")
    assert len(banner) == len(rows) + 2


def test_case_banner_lines_smoke(tmp_path) -> None:
    meta = {
        "case_name": "case",
        "solver": "simpleFoam",
        "status": "clean",
        "latest_time": "0",
        "mesh": "unknown",
        "parallel": "n/a",
        "foam_version": "v999",
        "case_header_version": "v999",
        "case_path": str(tmp_path / "case"),
        "log": "log.simpleFoam",
    }
    banner = layout.case_banner_lines(meta)
    assert any("Case:" in line for line in banner)

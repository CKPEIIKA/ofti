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


def test_banner_frame_fits_an_80_column_terminal() -> None:
    banner = layout.foam_style_banner("ofti", [("Left", "Right")])

    # curses cannot draw the last cell of a row, so every line must be <= 79.
    assert {len(line) for line in banner} == {79}
    assert banner[0].endswith("*\\")
    assert banner[-1].endswith("*/")


def test_case_banner_is_compact_and_honest_about_versions() -> None:
    meta = {
        "case_name": "cavity",
        "solver": "icoFoam",
        "status": "ran",
        "latest_time": "0.5",
        "mesh": "12345678 cells, skew=0.31, nonOrth=12",
        "cells": "12345678",
        "faces": "37000000",
        "points": "12500000",
        "foam_version": "unknown",
        "case_header_version": "2.0",
        "case_path": "/very/long/path/to/some/deeply/nested/study/cavity",
        "log": "log.icoFoam",
    }
    text = "\n".join(layout.case_banner_lines(meta))

    assert "Mesh: 12.3M cells 37.0M faces" in text
    assert text.count("12345678") == 0
    assert "Quality: skew=0.31 nonOrth=12" in text
    assert "Env: not loaded" in text
    assert "2.0" not in text
    assert "| Path: ..." in text
    assert "nested/study/cavity" in text


def test_case_banner_shows_release_header_and_running_durations() -> None:
    meta = {
        "case_name": "c",
        "foam_version": "v2206",
        "case_header_version": "v2512",
        "running": "yes",
        "sec_per_iter": "0.0012500000000000011",
        "eta_end": "3725",
        "eta_criteria": "75",
        "case_path": "/c",
    }
    text = "\n".join(layout.case_banner_lines(meta))

    assert "Env: v2206 (case v2512)" in text
    assert "s/iter=0.00125" in text
    assert "ETA end=1h02m criteria=1m15s" in text

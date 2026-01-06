from pathlib import Path

from of_tui.app import _detect_case_header_version


def _write_control_dict(tmp_path: Path, text: str) -> Path:
    case = tmp_path / "case"
    control = case / "system" / "controlDict"
    control.parent.mkdir(parents=True)
    control.write_text(text)
    return case


def test_detect_case_header_uses_banner_version(tmp_path: Path) -> None:
    text = (
        "/*--------------------------------*- C++ -*----------------------------------*\\\n"
        "| Version:  v2312                                                         |\n"
        "\\*---------------------------------------------------------------------------*/\n"
        "FoamFile\n"
        "{\n"
        "    version     2.0;\n"
        "}\n"
    )
    case = _write_control_dict(tmp_path, text)
    assert _detect_case_header_version(case) == "v2312"


def test_detect_case_header_falls_back_to_block(tmp_path: Path) -> None:
    text = (
        "FoamFile\n"
        "{\n"
        "    version     8.0;\n"
        "}\n"
    )
    case = _write_control_dict(tmp_path, text)
    assert _detect_case_header_version(case) == "8.0"


def test_detect_case_header_returns_unknown_when_missing(tmp_path: Path) -> None:
    text = (
        "FoamFile\n"
        "{\n"
        "    format      ascii;\n"
        "}\n"
    )
    case = _write_control_dict(tmp_path, text)
    assert _detect_case_header_version(case) == "unknown"

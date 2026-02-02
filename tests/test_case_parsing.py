from __future__ import annotations

from pathlib import Path

from ofti.core import case


def test_parse_skewness_and_non_orth() -> None:
    text = "Max skewness = 0.26\nnon-orthogonality max : 45\n"
    assert case.parse_max_skewness(text) == "0.26"
    assert case.parse_max_non_orth(text) == "45"
    assert case._format_float("0.259") == "0.26"


def test_preferred_log_name_picks_latest(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "system").mkdir()
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;\n")
    log1 = case_dir / "log.first"
    log2 = case_dir / "log.second"
    log1.write_text("a")
    log2.write_text("b")

    assert case.preferred_log_name(case_dir) == "log.second"

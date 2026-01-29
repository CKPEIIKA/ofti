from pathlib import Path

from ofti.core.case import preferred_log_name
from ofti.tools import _collect_postprocessing_files, _postprocessing_summary


def test_postprocessing_summary_counts(tmp_path: Path) -> None:
    root = tmp_path / "postProcessing"
    (root / "probes" / "0").mkdir(parents=True)
    (root / "probes" / "0" / "U").write_text("0 0 0\n")
    (root / "forces" / "0.1").mkdir(parents=True)
    (root / "forces" / "0.1" / "forces.dat").write_text("0 1\n")

    summary = _postprocessing_summary(root)
    joined = "\n".join(summary)
    assert "probes: times=1 files=1" in joined
    assert "forces: times=1 files=1" in joined


def test_collect_postprocessing_files(tmp_path: Path) -> None:
    root = tmp_path / "postProcessing"
    (root / "probes" / "0").mkdir(parents=True)
    file_path = root / "probes" / "0" / "U"
    file_path.write_text("0 0 0\n")

    files = _collect_postprocessing_files(root)
    assert files == [file_path]


def test_preferred_log_file(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    control = case_dir / "system" / "controlDict"
    control.parent.mkdir(parents=True)
    control.write_text(
        "\n".join(
            [
                "FoamFile",
                "{",
                "    version 2.0;",
                "    format ascii;",
                "    class dictionary;",
                "    location \"system\";",
                "    object controlDict;",
                "}",
                "application simpleFoam;",
                "",
            ],
        ),
    )
    log_path = case_dir / "log.simpleFoam"
    log_path.write_text("log")
    assert preferred_log_name(case_dir) == log_path.name

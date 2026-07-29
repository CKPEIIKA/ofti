import json
from pathlib import Path

import pytest

from ofti.app import cli_tools
from ofti.core.checkpoint import checkpoint_health, safe_reconstruct_time
from ofti.tools.checkpoint_service import (
    checkpoint_payload,
    quarantine_partial_payload,
    restart_plan_payload,
)


def _field(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("field\n", encoding="utf-8")


def test_checkpoint_reports_complete_partial_and_reconstructed_times(tmp_path: Path) -> None:
    case = tmp_path / "case"
    _field(case / "processor0" / "1" / "U")
    _field(case / "processor1" / "1" / "U")
    _field(case / "processor0" / "2" / "U")
    (case / "processor1" / "2").mkdir(parents=True)
    _field(case / "processor0" / "3" / "U")
    _field(case / "1" / "U")

    payload = checkpoint_payload(case)

    assert payload["ok"] is True
    assert payload["latest_complete_time"] == "1"
    assert payload["latest_processor_time"] == "3"
    assert payload["complete_times"] == ["1"]
    assert payload["quarantinable_times"] == ["2", "3"]
    assert payload["partial_times"] == [
        {"time": "2", "missing_processors": [], "empty_processors": ["processor1"]},
        {"time": "3", "missing_processors": ["processor1"], "empty_processors": []},
    ]
    assert payload["reconstructed_times"] == ["1"]


def test_checkpoint_validates_expected_processor_count(tmp_path: Path) -> None:
    case = tmp_path / "case"
    _field(case / "system" / "controlDict")
    _field(case / "processor0" / "1" / "U")

    with pytest.raises(ValueError, match="expected 2 processor directories"):
        checkpoint_health(case, expected_processors=2)


def test_safe_reconstruct_time_requires_complete_checkpoint() -> None:
    with pytest.raises(ValueError, match="no complete decomposed processor time"):
        safe_reconstruct_time({"latest_complete_time": None})


def test_checkpoint_quarantine_previews_then_moves_only_partial_times(tmp_path: Path) -> None:
    case = tmp_path / "case"
    _field(case / "system" / "controlDict")
    for processor in ("processor0", "processor1"):
        _field(case / processor / "1" / "U")
    _field(case / "processor0" / "2" / "U")

    preview = quarantine_partial_payload(case)
    applied = quarantine_partial_payload(case, apply=True)

    assert preview["applied"] is False
    assert len(preview["moves"]) == 1
    assert (case / "processor0" / "2" / "U").exists() is False
    assert (case / "processor0" / "1" / "U").is_file()
    assert Path(applied["moves"][0]["destination"]).joinpath("U").is_file()
    assert applied["checkpoint_after"]["quarantinable_times"] == []


def test_checkpoint_quarantine_refuses_to_move_only_partial_state(tmp_path: Path) -> None:
    case = tmp_path / "case"
    _field(case / "system" / "controlDict")
    _field(case / "processor0" / "2" / "U")
    (case / "processor1").mkdir()

    with pytest.raises(ValueError, match="without a complete checkpoint"):
        quarantine_partial_payload(case, apply=True)


def test_restart_plan_reports_latest_common_partial_newer_and_rank_resize(tmp_path: Path) -> None:
    case = tmp_path / "case"
    _field(case / "system" / "controlDict")
    (case / "system" / "decomposeParDict").write_text(
        "FoamFile\n{\nclass dictionary;\nobject decomposeParDict;\n}\nnumberOfSubdomains 2;\n",
        encoding="utf-8",
    )
    for processor in ("processor0", "processor1"):
        _field(case / processor / "10" / "U")
    _field(case / "processor0" / "20" / "U")

    payload = restart_plan_payload(case, expected_processors=2, target_processors=4)

    assert payload["safe_to_apply"] is True
    assert payload["mutated"] is False
    assert payload["latest_common_time"] == "10"
    assert [row["time"] for row in payload["partial_newer_times"]] == ["20"]
    assert payload["mpi"] == {
        "processor_dirs": ["processor0", "processor1"],
        "actual": 2,
        "configured": 2,
        "expected": 2,
        "target": 4,
        "contiguous": True,
        "consistent": True,
    }
    assert [row["action"] for row in payload["plan"]] == [
        "quarantine-partial",
        "reconstruct",
        "set-subdomains",
        "decompose",
        "resume-latest",
        "start",
    ]


def test_restart_plan_is_unsafe_for_mpi_size_mismatch(tmp_path: Path) -> None:
    case = tmp_path / "case"
    _field(case / "system" / "controlDict")
    (case / "system" / "decomposeParDict").write_text(
        "FoamFile\n{\nclass dictionary;\nobject decomposeParDict;\n}\nnumberOfSubdomains 4;\n",
        encoding="utf-8",
    )
    for processor in ("processor0", "processor1"):
        _field(case / processor / "10" / "U")

    payload = restart_plan_payload(case)

    assert payload["safe_to_apply"] is False
    assert payload["mpi"]["actual"] == 2
    assert payload["mpi"]["configured"] == 4
    assert payload["mpi"]["consistent"] is False


def test_restart_plan_cli_exposes_read_only_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = tmp_path / "case"
    _field(case / "system" / "controlDict")
    (case / "system" / "decomposeParDict").write_text(
        "FoamFile\n{\nclass dictionary;\nobject decomposeParDict;\n}\nnumberOfSubdomains 2;\n",
        encoding="utf-8",
    )
    for processor in ("processor0", "processor1"):
        _field(case / processor / "10" / "U")

    code = cli_tools.main(
        ["run", "restart-plan", str(case), "--from", "2", "--to", "4", "--json"],
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["command"] == "run restart-plan"
    assert payload["safe_to_apply"] is True
    assert payload["mutated"] is False
    assert (case / "10").exists() is False

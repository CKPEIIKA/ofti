from pathlib import Path

import pytest

from ofti.core.checkpoint import checkpoint_health, safe_reconstruct_time
from ofti.tools.checkpoint_service import checkpoint_payload


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

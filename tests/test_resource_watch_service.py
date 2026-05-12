from __future__ import annotations

from pathlib import Path

from ofti.tools.resource_watch_service import resource_watch_payload


def test_resource_watch_payload_counts_runtime_artifacts(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    (case / "0.1").mkdir()
    (case / "1").mkdir()
    (case / "processor0").mkdir()
    (case / "log.simpleFoam").write_text("x" * 10)

    payload = resource_watch_payload(case)

    assert payload["time_dirs"] == 2
    assert payload["processor_dirs"] == 1
    assert payload["log_bytes"] == 10
    assert payload["risk"] == "low"
    assert payload["logs"] == [{"log": "log.simpleFoam", "bytes": 10, "size": "10B"}]


def test_resource_watch_payload_handles_missing_case(tmp_path: Path) -> None:
    payload = resource_watch_payload(tmp_path / "missing")

    assert payload["free_bytes"] is None
    assert payload["time_dirs"] == 0
    assert payload["logs"] == []

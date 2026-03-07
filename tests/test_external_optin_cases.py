from __future__ import annotations

import os
from pathlib import Path

import pytest

from ofti.tools.cli_tools import knife, run, watch


def _external_cases() -> list[Path]:
    raw = os.environ.get("OFTI_EXTERNAL_CASES", "").strip()
    if not raw:
        return []
    paths: list[Path] = []
    for part in raw.split(":"):
        text = part.strip()
        if not text:
            continue
        path = Path(text).expanduser().resolve()
        if path.is_dir():
            paths.append(path)
    return paths


@pytest.fixture(scope="module")
def external_cases() -> list[Path]:
    paths = _external_cases()
    if not paths:
        pytest.skip(
            "Set OFTI_EXTERNAL_CASES=/path/to/case[:/path/to/other_case] to enable external integration checks.",
        )
    return paths


def test_external_knife_status(external_cases: list[Path]) -> None:
    payload = knife.status_payload(external_cases[0])
    assert payload["case"] == str(external_cases[0])
    assert "jobs_running" in payload


def test_external_watch_jobs(external_cases: list[Path]) -> None:
    payload = watch.jobs_payload(external_cases[0], include_all=True)
    assert payload["case"] == str(external_cases[0])
    assert isinstance(payload["jobs"], list)


def test_external_run_tool_catalog(external_cases: list[Path]) -> None:
    payload = run.tool_catalog_payload(external_cases[0])
    assert payload["case"] == str(external_cases[0])
    assert isinstance(payload["tools"], list)


def test_external_knife_compare_when_two_cases(external_cases: list[Path]) -> None:
    if len(external_cases) < 2:
        pytest.skip("Need at least two external cases for compare.")
    payload = knife.compare_payload(external_cases[0], external_cases[1])
    assert payload["left_case"] == str(external_cases[0])
    assert payload["right_case"] == str(external_cases[1])
    assert "diff_count" in payload

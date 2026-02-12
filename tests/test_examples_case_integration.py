from __future__ import annotations

from pathlib import Path

from ofti.core.case_meta import case_metadata_quick
from ofti.core.entry_io import list_keywords
from ofti.foam.openfoam import OpenFOAMError, discover_case_files, verify_case


def _example_cases() -> list[Path]:
    root = Path("examples")
    if not root.is_dir():
        return []
    return sorted(
        path for path in root.iterdir() if path.is_dir() and (path / "system" / "controlDict").is_file()
    )


def test_examples_cases_basic_integration() -> None:
    cases = _example_cases()
    assert cases, "Expected at least one valid OpenFOAM case in examples/"

    for case_path in cases:
        meta = case_metadata_quick(case_path)
        assert meta["case_name"] == case_path.name
        assert meta["solver"]

        sections = discover_case_files(case_path)
        total_files = sum(len(files) for files in sections.values())
        assert total_files > 0

        keyword_attempts = 0
        keyword_successes = 0
        for files in sections.values():
            for file_path in files[:2]:
                # Best-effort smoke check: some dictionary variants may not be supported by list_keywords.
                keyword_attempts += 1
                try:
                    _ = list_keywords(file_path)
                except OpenFOAMError:
                    continue
                keyword_successes += 1

        assert keyword_attempts > 0
        assert keyword_successes > 0

        results = verify_case(case_path)
        assert len(results) == total_files
        assert all(result.checked for result in results.values())

from __future__ import annotations

from pathlib import Path

from ofti.core.case_fingerprint import case_fingerprint


def test_case_fingerprint_hashes_case_setup_roots(tmp_path: Path) -> None:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "constant").mkdir()
    (case / "0").mkdir()
    (case / "system" / "controlDict").write_text("application simpleFoam;\n")
    (case / "constant" / "transportProperties").write_text("nu 1e-5;\n")
    (case / "0" / "U").write_text("internalField uniform (1 0 0);\n")

    first = case_fingerprint(case)
    second = case_fingerprint(case)

    assert first["hash"] == second["hash"]
    assert first["files"] == 3
    assert first["skipped"] == 0


def test_case_fingerprint_skips_large_files(tmp_path: Path) -> None:
    case = tmp_path / "case"
    (case / "constant").mkdir(parents=True)
    (case / "constant" / "big").write_text("abcdef")

    payload = case_fingerprint(case, max_file_bytes=2)

    assert payload["files"] == 0
    assert payload["skipped"] == 1

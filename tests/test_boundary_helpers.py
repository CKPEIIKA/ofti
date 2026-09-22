from __future__ import annotations

import gzip
from pathlib import Path

from ofti.core import boundary


def test_zero_dir_prefers_zero(tmp_path: Path) -> None:
    zero = tmp_path / "0"
    zero.mkdir()
    (tmp_path / "0.orig").mkdir()
    assert boundary.zero_dir(tmp_path) == zero


def test_zero_dir_uses_zero_orig_when_zero_is_missing(tmp_path: Path) -> None:
    zero_orig = tmp_path / "0.orig"
    zero_orig.mkdir()

    assert boundary.zero_dir(tmp_path) == zero_orig


def test_list_field_files_returns_empty_without_initial_directory(tmp_path: Path) -> None:
    assert boundary.list_field_files(tmp_path) == []


def test_list_field_files_filters(tmp_path: Path) -> None:
    zero = tmp_path / "0"
    zero.mkdir()
    (zero / ".hidden").write_text("ignore")
    (zero / "U").write_text("field")
    (zero / "p").write_text("field")
    (zero / "temp~").write_text("backup")

    fields = boundary.list_field_files(tmp_path)
    assert fields == ["U", "p"]


def test_list_field_files_resolves_compressed_fields_without_duplicates(tmp_path: Path) -> None:
    zero = tmp_path / "0"
    zero.mkdir()
    (zero / "U").write_text("FoamFile { format ascii; class volVectorField; }\ninternalField uniform (0 0 0);\n")
    compressed = b"FoamFile { format binary; class volScalarField; }\ninternalField uniform 1;\n"
    with gzip.open(zero / "p.gz", "wb") as handle:
        handle.write(compressed)
    with gzip.open(zero / "U.gz", "wb") as handle:
        handle.write(compressed)

    assert boundary.list_field_files(tmp_path) == ["U", "p"]
    assert boundary.field_file_path(zero, "p") == zero / "p.gz"


def test_list_field_files_reads_compressed_zero_orig_fields(tmp_path: Path) -> None:
    zero_orig = tmp_path / "0.orig"
    zero_orig.mkdir()
    field_header = b"FoamFile { format binary; class volScalarField; }\ninternalField uniform 1;\n"
    for name in ("U", "p"):
        with gzip.open(zero_orig / f"{name}.gz", "wb") as compressed:
            compressed.write(field_header)

    assert boundary.list_field_files(tmp_path) == ["U", "p"]
    assert boundary.field_file_path(boundary.zero_dir(tmp_path), "p") == zero_orig / "p.gz"

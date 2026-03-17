from pathlib import Path

import pytest

from ofti.foamlib import postprocessing as fp


def test_postprocessing_requires_extras(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(fp, "FOAMLIB_POSTPROCESSING", False)
    with pytest.raises(RuntimeError):
        fp.list_table_sources(tmp_path)


def test_postprocessing_list_and_load(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _Source:
        def __init__(self, file_name: str, folder: str, times: list[str]) -> None:
            self.file_name = file_name
            self.folder = folder
            self.time_resolved = True
            self.times = times

    class _Table:
        def __init__(self) -> None:
            self.shape = (2, 2)
            self.columns = ["t", "Ux"]

        def head(self, _rows: int):
            return self

        def to_string(self, *, index: bool = False) -> str:
            _ = index
            return "0 1\n1 2"

    monkeypatch.setattr(fp, "FOAMLIB_POSTPROCESSING", True)
    monkeypatch.setattr(
        fp,
        "list_function_objects",
        lambda _case: {"probes--U.dat": _Source("U.dat", "probes", ["0", "1"])},
    )
    monkeypatch.setattr(fp, "load_tables", lambda *_a, **_k: _Table())

    rows = fp.list_table_sources(tmp_path)
    assert rows[0]["id"] == "probes--U.dat"
    assert rows[0]["time_count"] == 2

    loaded = fp.load_table_source(tmp_path, "probes--U.dat")
    assert loaded["rows"] == 2
    assert loaded["columns"] == ["t", "Ux"]

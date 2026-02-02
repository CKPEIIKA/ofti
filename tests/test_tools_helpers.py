from pathlib import Path

import pytest

from ofti.core.postprocessing import _looks_like_time
from ofti.tools.diagnostics import _directory_size, _human_size
from ofti.tools.logs_analysis import _sparkline
from ofti.tools.logs_fields import _summarize_internal_field
from ofti.tools.logs_select import _tail_text


def test_tail_text_limits_lines() -> None:
    text = "\n".join([f"line{i}" for i in range(30)])
    tail = _tail_text(text, max_lines=5)
    assert "line29" in tail
    assert "lines omitted" in tail


def test_looks_like_time() -> None:
    assert _looks_like_time("0.1") is True
    assert _looks_like_time("10") is True
    assert _looks_like_time("not-a-time") is False


def test_summarize_internal_field_scalar() -> None:
    lines = _summarize_internal_field(3.14)
    assert "Internal field" in lines[0]
    assert "3.14" in lines[0]


def test_summarize_internal_field_vector() -> None:
    lines = _summarize_internal_field([1, 2, 3])
    assert "vector" in lines[0]


def test_sparkline_outputs_chars() -> None:
    line = _sparkline([0.1, 0.2, 0.3], width=5)
    assert line


def test_directory_size_and_human_size(tmp_path: Path) -> None:
    file_path = tmp_path / "a.txt"
    file_path.write_text("hello")
    size = _directory_size(tmp_path)
    assert size >= 5
    assert _human_size(size).endswith("B")


def test_summarize_internal_field_array() -> None:
    np = pytest.importorskip("numpy")
    arr = np.array([0.0, 1.0, 2.0])
    lines = _summarize_internal_field(arr)
    assert "min=" in lines[0] or "shape=" in lines[0]

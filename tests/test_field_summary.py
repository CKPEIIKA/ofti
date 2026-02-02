from pathlib import Path

import pytest

from ofti.foamlib import adapter as foamlib_integration
from ofti.tools.logs_fields import _field_summary_lines, _latest_time_dir


@pytest.mark.skipif(not foamlib_integration.available(), reason="foamlib required")
def test_field_summary_lines_for_latest_time() -> None:
    case_path = Path("examples/of_example")
    time_dir = _latest_time_dir(case_path)
    assert time_dir is not None
    field_path = time_dir / "U"
    lines = _field_summary_lines(case_path, field_path)
    joined = "\n".join(lines)
    assert "FIELD SUMMARY" in joined
    assert "Class:" in joined
    assert "Internal field" in joined

from pathlib import Path

import pytest

from ofti.core.entry_io import write_entry
from ofti.foamlib import adapter as foamlib_integration


def _write_control_dict(path: Path, entries: dict[str, str]) -> None:
    lines = [
        "FoamFile",
        "{",
        "    version 2.0;",
        "    format ascii;",
        "    class dictionary;",
        "    location \"system\";",
        "    object controlDict;",
        "}",
    ]
    for key, value in entries.items():
        lines.append(f"{key} {value};")
    lines.append("")
    path.write_text("\n".join(lines))


@pytest.mark.skipif(not foamlib_integration.available(), reason="foamlib required")
def test_write_entry_logs_edit(tmp_path: Path) -> None:
    case_root = tmp_path / "case"
    control = case_root / "system" / "controlDict"
    control.parent.mkdir(parents=True)
    _write_control_dict(control, {"application": "simpleFoam"})

    assert write_entry(control, "application", "pimpleFoam")

    log_path = case_root / ".ofti" / "edits.log"
    assert log_path.exists()
    text = log_path.read_text()
    assert "system/controlDict application" in text
    assert "simpleFoam" in text
    assert "pimpleFoam" in text

from __future__ import annotations

from pathlib import Path

from ofti.ui_curses import thermo_wizard


def test_entry_path_for_uses_thermotype_prefix() -> None:
    assert thermo_wizard._entry_path_for("transport") == "thermoType.transport"
    assert thermo_wizard._entry_path_for("type") == "thermoType.type"


def test_slot_validator_rejects_empty_and_blocks() -> None:
    assert thermo_wizard._slot_validator("") is not None
    assert thermo_wizard._slot_validator("{ type hePsiThermo; }") is not None
    assert thermo_wizard._slot_validator("heRho2Thermo") is None


def test_dict_path_for_uses_thermophysical_file(tmp_path: Path) -> None:
    case_path = tmp_path / "case"
    expected = case_path / "constant" / "thermophysicalProperties"
    assert thermo_wizard._dict_path_for(case_path) == expected

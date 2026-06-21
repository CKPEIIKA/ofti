# ruff: noqa: INP001
from __future__ import annotations

import sys
from pathlib import Path

MOD_SRC = Path(__file__).resolve().parents[1] / "src"
if str(MOD_SRC) not in sys.path:
    sys.path.insert(0, str(MOD_SRC))

from ofti_hy2foam_mod.plugin import register  # noqa: E402
from ofti_hy2foam_mod.preflight import nn_preflight_payload  # noqa: E402

from ofti.plugins import PluginRegistry  # noqa: E402


def _case(path: Path) -> Path:
    (path / "system").mkdir(parents=True)
    (path / "constant").mkdir()
    return path


def test_mod_plugin_registers_nn_preflight_command() -> None:
    registry = PluginRegistry()

    register(registry)

    assert "hy2foam-mod-preflight" in registry.knife_commands


def test_nn_species_order_mismatch_is_detected(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    (case / "system" / "nnModel").write_text(
        "inputOrder (N2 O2 NO N O);\n", encoding="utf-8",
    )
    (case / "constant" / "nnTransport").write_text(
        "outputOrder (O2 N2 NO N O);\n", encoding="utf-8",  # reordered -> mismatch
    )

    payload = nn_preflight_payload(case)

    assert payload["ok"] is False
    assert payload["check"]["status"] == "FAIL"
    assert "outputOrder" in payload["check"]["detail"]


def test_nn_species_order_consistent_passes(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    (case / "system" / "nnModel").write_text(
        "inputOrder (N2 O2 NO N O);\n", encoding="utf-8",
    )
    (case / "constant" / "nnTransport").write_text(
        "outputOrder (N2 O2 NO N O);\n", encoding="utf-8",
    )

    payload = nn_preflight_payload(case)

    assert payload["ok"] is True
    assert payload["check"]["status"] == "PASS"

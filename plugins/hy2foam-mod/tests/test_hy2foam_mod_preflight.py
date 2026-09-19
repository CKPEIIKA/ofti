from __future__ import annotations

from pathlib import Path

from ofti_hy2foam_mod.plugin import register
from ofti_hy2foam_mod.preflight import nn_preflight_payload

from ofti.plugins import PluginRegistry


def _case(path: Path) -> Path:
    (path / "system").mkdir(parents=True)
    (path / "constant").mkdir()
    return path


def test_mod_plugin_registers_nn_preflight_command() -> None:
    registry = PluginRegistry()

    register(registry)

    assert "hy2foam-mod-preflight" in registry.knife_commands
    assert "hy2foam-mod" in registry.bundle_hints


def test_mod_bundle_hints_for_nncompiled_cases(tmp_path: Path) -> None:
    registry = PluginRegistry()
    register(registry)
    case = _case(tmp_path / "case")
    (case / "constant" / "nnTransport").write_text("precompiledModel model.so;\n")

    hints = registry.bundle_hints["hy2foam-mod"].bundle_hints(case)

    assert any("NNcompiled runtime" in hint for hint in hints)


def test_nn_species_order_mismatch_is_detected(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    (case / "system" / "nnModel").write_text(
        "inputOrder (N2 O2 NO N O);\n",
        encoding="utf-8",
    )
    (case / "constant" / "nnTransport").write_text(
        "outputOrder (O2 N2 NO N O);\n",
        encoding="utf-8",  # reordered -> mismatch
    )

    payload = nn_preflight_payload(case)

    assert payload["ok"] is False
    assert payload["check"]["status"] == "FAIL"
    assert "outputOrder" in payload["check"]["detail"]


def test_nn_species_order_consistent_passes(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    (case / "system" / "nnModel").write_text(
        "inputOrder (N2 O2 NO N O);\n",
        encoding="utf-8",
    )
    (case / "constant" / "nnTransport").write_text(
        "outputOrder (N2 O2 NO N O);\n",
        encoding="utf-8",
    )

    payload = nn_preflight_payload(case)

    assert payload["ok"] is True
    assert payload["check"]["status"] == "PASS"

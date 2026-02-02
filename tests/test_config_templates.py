from __future__ import annotations

from pathlib import Path

from ofti.app import config_templates


def test_missing_config_templates_detects_missing(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;\n")

    missing = config_templates.missing_config_templates(case_dir)
    labels = {label for label, _path, _obj in missing}
    assert "fvSchemes" in labels
    assert "fvSolution" in labels


def test_write_config_template_stub(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    target = case_dir / "system" / "controlDict"

    monkeypatch.setattr(config_templates, "write_example_template", lambda *_a, **_k: False)
    source = config_templates.write_config_template(case_dir, target, "controlDict")

    assert source == "stub"
    content = target.read_text()
    assert "FoamFile" in content

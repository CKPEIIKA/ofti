from pathlib import Path

from ofti.core import templates


def test_load_example_template_from_temp_root(monkeypatch, tmp_path: Path) -> None:
    examples = tmp_path / "examples"
    case = examples / "caseA"
    target = case / "system" / "controlDict"
    target.parent.mkdir(parents=True)
    target.write_text("controlDict content")

    monkeypatch.setattr(templates, "_examples_root", lambda: examples)

    content = templates.load_example_template(Path("system/controlDict"))
    assert content == "controlDict content"


def test_write_example_template(monkeypatch, tmp_path: Path) -> None:
    examples = tmp_path / "examples"
    case = examples / "caseA"
    source = case / "system" / "fvSolution"
    source.parent.mkdir(parents=True)
    source.write_text("fvSolution content")

    monkeypatch.setattr(templates, "_examples_root", lambda: examples)

    dest = tmp_path / "caseB" / "system" / "fvSolution"
    ok = templates.write_example_template(dest, Path("system/fvSolution"))
    assert ok
    assert dest.read_text() == "fvSolution content"


def test_find_example_file(monkeypatch, tmp_path: Path) -> None:
    examples = tmp_path / "examples"
    case = examples / "caseA"
    source = case / "constant" / "transportProperties"
    source.parent.mkdir(parents=True)
    source.write_text("transportProperties content")

    monkeypatch.setattr(templates, "_examples_root", lambda: examples)

    found = templates.find_example_file(Path("constant/transportProperties"))
    assert found is not None
    assert found.read_text() == "transportProperties content"

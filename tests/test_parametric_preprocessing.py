from pathlib import Path

from ofti.foamlib import parametric as param


def test_build_parametric_cases_preprocessing(monkeypatch, tmp_path: Path) -> None:
    created: list[Path] = []

    class DummyAssignment:
        def __init__(self, instruction, value) -> None:
            self.instruction = instruction
            self.value = value

    class DummyInstruction:
        def __init__(self, file_name, keys) -> None:
            self.file_name = file_name
            self.keys = keys

    class DummyCaseModifier:
        def __init__(self, template_case, output_case, key_value_pairs, case_parameters) -> None:
            self.template_case = template_case
            self.output_case = output_case
            self.key_value_pairs = key_value_pairs
            self.case_parameters = case_parameters

        def create_case(self) -> None:
            self.output_case.mkdir(parents=True, exist_ok=True)

        def modify_case(self) -> None:
            created.append(self.output_case)

    class DummyCaseParameter:
        def __init__(self, category, name) -> None:
            self.category = category
            self.name = name

    monkeypatch.setattr(param, "FOAMLIB_PREPROCESSING", True)
    monkeypatch.setattr(param, "FoamDictAssignment", DummyAssignment)
    monkeypatch.setattr(param, "FoamDictInstruction", DummyInstruction)
    monkeypatch.setattr(param, "CaseModifier", DummyCaseModifier)
    monkeypatch.setattr(param, "CaseParameter", DummyCaseParameter)

    case_path = tmp_path / "case"
    case_path.mkdir()
    (case_path / "system").mkdir()
    (case_path / "system" / "controlDict").write_text("FoamFile{}")

    results = param.build_parametric_cases(
        case_path,
        Path("system/controlDict"),
        "application",
        ["simpleFoam"],
    )

    assert results
    assert created
    assert results[0].name.startswith("case_application_simpleFoam")

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


def test_build_parametric_cases_from_csv(monkeypatch, tmp_path: Path) -> None:
    class DummyCase:
        def __init__(self, output_case: Path) -> None:
            self.output_case = output_case

    class DummyStudy:
        def __init__(self, output_folder: Path) -> None:
            self.output_folder = output_folder
            self.cases = [DummyCase(output_folder / "csv_case")]

        def create_study(self, study_base_folder: Path) -> None:
            assert study_base_folder == self.output_folder

    monkeypatch.setattr(param, "FOAMLIB_PREPROCESSING", True)
    def _csv_generator(**kwargs):
        return DummyStudy(kwargs["output_folder"])

    monkeypatch.setattr(param, "csv_generator", _csv_generator)

    case_path = tmp_path / "case"
    case_path.mkdir()
    csv_path = case_path / "study.csv"
    csv_path.write_text("a,b\n1,2\n")

    created = param.build_parametric_cases_from_csv(case_path, Path("study.csv"))
    assert created == [case_path.parent / "csv_case"]


def test_build_parametric_cases_from_grid(monkeypatch, tmp_path: Path) -> None:
    class DummyInstruction:
        def __init__(self, file_name, keys) -> None:
            self.file_name = file_name
            self.keys = keys

    class DummyGridCaseParameter:
        def __init__(self, name, values) -> None:
            self.name = name
            self.values = values

    class DummyGridParameter:
        def __init__(self, parameter_name, modify_dict, parameters) -> None:
            self.parameter_name = parameter_name
            self.modify_dict = modify_dict
            self.parameters = parameters

    class DummyCase:
        def __init__(self, output_case: Path) -> None:
            self.output_case = output_case

    class DummyStudy:
        def __init__(self, output_folder: Path) -> None:
            self.cases = [DummyCase(output_folder / "grid_case")]

        def create_study(self, study_base_folder: Path) -> None:
            _ = study_base_folder

    monkeypatch.setattr(param, "FOAMLIB_PREPROCESSING", True)
    monkeypatch.setattr(param, "FoamDictInstruction", DummyInstruction)
    monkeypatch.setattr(param, "GridCaseParameter", DummyGridCaseParameter)
    monkeypatch.setattr(param, "GridParameter", DummyGridParameter)
    def _grid_generator(**kwargs):
        return DummyStudy(kwargs["output_folder"])

    monkeypatch.setattr(param, "grid_generator", _grid_generator)

    case_path = tmp_path / "case"
    case_path.mkdir()
    created = param.build_parametric_cases_from_grid(
        case_path,
        [
            {
                "dict_path": "system/controlDict",
                "entry": "application",
                "values": ["simpleFoam", "pisoFoam"],
            },
        ],
    )
    assert created == [case_path.parent / "grid_case"]

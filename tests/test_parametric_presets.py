from pathlib import Path

from ofti.tools.postprocessing import _read_parametric_presets


def test_read_parametric_presets_pipe_format(tmp_path: Path) -> None:
    path = tmp_path / "ofti.parametric"
    path.write_text("speed | system/controlDict | application | simpleFoam, pimpleFoam\n")
    presets, errors = _read_parametric_presets(path)
    assert not errors
    assert presets[0].name == "speed"
    assert presets[0].values == ["simpleFoam", "pimpleFoam"]


def test_read_parametric_presets_colon_format(tmp_path: Path) -> None:
    path = tmp_path / "ofti.parametric"
    path.write_text("test: system/controlDict application simpleFoam, pimpleFoam\n")
    presets, errors = _read_parametric_presets(path)
    assert not errors
    assert presets[0].entry == "application"

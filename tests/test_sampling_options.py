from pathlib import Path

from ofti.tools.postprocessing import _sampling_options


def test_sampling_options_enabled(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    topo = case_dir / "system" / "topoSetDict"
    topo.parent.mkdir(parents=True)
    topo.write_text("FoamFile {}")

    options = _sampling_options(case_dir)
    topo_opt = next(opt for opt in options if "topoSet" in opt.label)
    sample_opt = next(opt for opt in options if "sample" in opt.label)
    assert topo_opt.enabled is True
    assert sample_opt.enabled is False

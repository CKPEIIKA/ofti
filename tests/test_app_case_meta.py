from pathlib import Path

from ofti.app.helpers import menu_scroll
from ofti.app.screens import editor as editor_screen
from ofti.app.screens import main as main_screen
from ofti.app.state import AppState
from ofti.core.case_meta import case_metadata_quick


def _make_case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "case"
    control = case_dir / "system" / "controlDict"
    control.parent.mkdir(parents=True)
    control.write_text(
        "\n".join(
            [
                "FoamFile",
                "{",
                "    version 2.0;",
                "    format ascii;",
                "    class dictionary;",
                '    location "system";',
                "    object controlDict;",
                "}",
                "application simpleFoam;",
                "",
            ],
        ),
    )
    return case_dir


def test_case_meta_quick(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    meta = case_metadata_quick(case_dir)
    assert meta["case_name"] == "case"
    assert meta["solver"] == "simpleFoam"
    assert meta["disk"] == "deferred"


def test_case_meta_quick_avoids_heavy_mesh_and_time_scans(tmp_path: Path, monkeypatch) -> None:
    case_dir = _make_case(tmp_path)
    (case_dir / "2").mkdir()
    monkeypatch.setattr(
        "ofti.core.case_meta.mesh_counts",
        lambda _case: (_ for _ in ()).throw(AssertionError("no full mesh scan")),
    )
    monkeypatch.setattr(
        "ofti.core.case_meta.detect_openfoam_version",
        lambda: (_ for _ in ()).throw(AssertionError("no foamVersion subprocess")),
    )

    meta = case_metadata_quick(case_dir)

    assert meta["latest_time"] == "2"
    assert meta["cells"] == "n/a"


def test_case_metadata_cached_uses_placeholder(tmp_path: Path, monkeypatch) -> None:
    case_dir = _make_case(tmp_path)
    state = AppState()
    _ = monkeypatch
    meta = main_screen.case_metadata_cached(case_dir, state)
    assert meta["case_name"] == "case"


def test_simple_case_sections(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    (case_dir / "constant").mkdir()
    (case_dir / "constant" / "transportProperties").write_text("FoamFile {}")
    sections = editor_screen.simple_case_sections(case_dir)
    assert "system" in sections
    assert any(p.name == "controlDict" for p in sections["system"])


def test_scan_zero_dirs(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    (case_dir / "0").mkdir()
    (case_dir / "0.orig").mkdir()
    (case_dir / "junk").mkdir()
    zero_dirs = editor_screen.scan_zero_dirs(case_dir)
    names = {p.name for p in zero_dirs}
    assert "0" in names
    assert "0.orig" in names


def test_menu_scroll_wrapper(tmp_path: Path) -> None:
    _ = tmp_path
    # Use a stub screen with fixed size.
    class Screen:
        def getmaxyx(self):
            return (10, 80)

    scroll = menu_scroll(5, 0, Screen(), total=50, header_rows=2)
    assert scroll >= 0

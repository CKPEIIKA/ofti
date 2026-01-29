from __future__ import annotations

from ofti.core.boundary import BoundaryMatrix
from ofti.ui_curses import boundary_matrix as bm


def test_visible_patches_filters_processor_and_empty() -> None:
    matrix = BoundaryMatrix(
        fields=["U"],
        patches=["inlet", "processor0", "frontAndBack", "wall"],
        patch_types={"frontAndBack": "empty", "wall": "wall", "inlet": "patch"},
        data={},
    )
    visible = bm._visible_patches(matrix, hide_special=True)
    assert "inlet" in visible
    assert "wall" in visible
    assert "processor0" not in visible
    assert "frontAndBack" not in visible


def test_snippet_options_for_velocity() -> None:
    options = bm._snippet_options("U")
    names = [item[0] for item in options]
    assert any("inlet" in name for name in names)

from __future__ import annotations

from ofti.core import boundary


def test_parse_boundary_text_basic() -> None:
    text = """
2
(
    inlet
    {
        type patch;
        nFaces 4;
        startFace 0;
    }
    wall
    {
        type wall;
        nFaces 8;
        startFace 4;
    }
)
"""
    patches, patch_types = boundary.parse_boundary_text(text)
    assert patches == ["inlet", "wall"]
    assert patch_types == {"inlet": "patch", "wall": "wall"}

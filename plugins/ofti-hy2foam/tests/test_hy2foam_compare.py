# ruff: noqa: INP001
from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PLUGIN_SRC) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SRC))

from ofti_hy2foam.compare import (  # noqa: E402
    compare_preflight_payload,
    latest_common_time,
    patch_compare_payload,
)


def _case(path: Path, *, mesh_marker: str) -> Path:
    for time_name in ("0", "0.5", "1"):
        (path / time_name).mkdir(parents=True)
    mesh = path / "constant" / "polyMesh"
    mesh.mkdir(parents=True)
    for name in ("boundary", "points", "faces", "owner", "neighbour"):
        (mesh / name).write_text(f"{name}:{mesh_marker}\n", encoding="utf-8")
    return path


def _patch_scalar(path: Path, value: float) -> None:
    path.write_text(
        "FoamFile{ version 2.0; format ascii; class volScalarField; }\n"
        f"internalField uniform {value};\n"
        "boundaryField\n{\n"
        "  wall\n  {\n"
        "    type fixedValue;\n"
        f"    value uniform {value};\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )


def test_latest_common_time_and_same_mesh_payload(tmp_path: Path) -> None:
    left = _case(tmp_path / "left", mesh_marker="same")
    right = _case(tmp_path / "right", mesh_marker="same")
    (right / "1").rmdir()

    payload = compare_preflight_payload(left, right)

    assert latest_common_time(left, right) == "0.5"
    assert payload["ok"] is True
    assert payload["same_mesh"]["same"] is True


def test_compare_preflight_flags_mesh_mismatch(tmp_path: Path) -> None:
    left = _case(tmp_path / "left", mesh_marker="left")
    right = _case(tmp_path / "right", mesh_marker="right")

    payload = compare_preflight_payload(left, right)

    assert payload["ok"] is False
    assert payload["same_mesh"]["same"] is False


def test_patch_compare_uses_latest_common_time_and_patch_values(tmp_path: Path) -> None:
    left = _case(tmp_path / "left", mesh_marker="same")
    right = _case(tmp_path / "right", mesh_marker="same")
    (right / "1").rmdir()
    for case, value in ((left, 10.0), (right, 12.0)):
        for field in ("wallHeatFlux", "qCond", "qDiff", "p"):
            _patch_scalar(case / "0.5" / field, value)

    payload = patch_compare_payload(left, right, patch="wall")

    assert payload["ok"] is True
    assert payload["time"] == "0.5"
    assert payload["patch"] == "wall"
    assert payload["same"] is False
    assert payload["fields"][0]["max_abs"] == 2.0

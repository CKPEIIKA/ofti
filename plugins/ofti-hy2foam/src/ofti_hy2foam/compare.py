from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ofti.core.field_compare import compare_fields_payload
from ofti.core.times import time_directories

from .presets import TRANSPORT, TWO_TEMPERATURE, WALL

MESH_FILES = ("boundary", "points", "faces", "owner", "neighbour")
PATCH_PRESETS = {preset.name: preset.fields for preset in (TRANSPORT, TWO_TEMPERATURE, WALL)}


class Hy2FoamComparePreflightCommand:
    name = "hy2foam-compare-check"

    def add_parser(self, subparsers) -> None:
        parser = subparsers.add_parser(
            "hy2foam-compare-check",
            help="Check hy2Foam case pair before cellwise field comparison",
        )
        parser.add_argument("left_case", type=Path)
        parser.add_argument("right_case", type=Path)
        parser.set_defaults(func=self.run)

    def run(self, args) -> int:
        payload = compare_preflight_payload(args.left_case, args.right_case)
        print(f"latest_common_time={payload['latest_common_time']}")
        print(f"same_mesh={payload['same_mesh']['same']}")
        return 0 if payload["ok"] else 1


class Hy2FoamPatchCompareCommand:
    name = "hy2foam-patch-compare"

    def add_parser(self, subparsers) -> None:
        parser = subparsers.add_parser(
            "hy2foam-patch-compare",
            help="Compare hy2Foam patch field values between two same-mesh cases",
        )
        parser.add_argument("left_case", type=Path)
        parser.add_argument("right_case", type=Path)
        parser.add_argument("--patch", required=True)
        parser.add_argument("--preset", default="hy2foam-wall")
        parser.add_argument("--time", default=None)
        parser.set_defaults(func=self.run)

    def run(self, args) -> int:
        payload = patch_compare_payload(
            args.left_case,
            args.right_case,
            patch=str(args.patch),
            preset=str(args.preset),
            time_name=getattr(args, "time", None),
        )
        print(f"time={payload['time']} patch={payload['patch']} same={payload['same']}")
        for error in payload.get("errors", []):
            print(f"error={error}")
        return 0 if payload["ok"] else 1


def compare_preflight_payload(left_case: Path, right_case: Path) -> dict[str, Any]:
    common_time = latest_common_time(left_case, right_case)
    mesh = same_mesh_payload(left_case, right_case)
    return {
        "left_case": str(left_case),
        "right_case": str(right_case),
        "ok": common_time is not None and bool(mesh["same"]),
        "latest_common_time": common_time,
        "same_mesh": mesh,
    }


def patch_compare_payload(
    left_case: Path,
    right_case: Path,
    *,
    patch: str,
    preset: str = "hy2foam-wall",
    time_name: str | None = None,
    abs_tol: float = 1e-300,
    rel_tol: float = 1e-12,
) -> dict[str, Any]:
    preflight = compare_preflight_payload(left_case, right_case)
    selected_time = time_name or preflight["latest_common_time"]
    if selected_time is None:
        return {
            **preflight,
            "time": None,
            "patch": patch,
            "preset": preset,
            "ok": False,
            "same": False,
            "errors": ["no common time directories"],
            "fields": [],
        }
    fields = list(PATCH_PRESETS[preset]) if preset in PATCH_PRESETS else None
    payload = compare_fields_payload(
        left_case,
        right_case,
        time_name=str(selected_time),
        fields=fields,
        preset=None if fields else preset,
        patch=patch,
        abs_tol=abs_tol,
        rel_tol=rel_tol,
    )
    payload["preset"] = preset
    payload["preflight"] = preflight
    if not bool(preflight["same_mesh"]["same"]):
        payload["ok"] = False
        payload.setdefault("errors", []).append("mesh mismatch")
    return payload


def latest_common_time(left_case: Path, right_case: Path) -> str | None:
    left = {path.name for path in time_directories(left_case)}
    right = {path.name for path in time_directories(right_case)}
    common = left & right
    if not common:
        return None
    return max(common, key=_time_sort_key)


def same_mesh_payload(left_case: Path, right_case: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    same = True
    for name in MESH_FILES:
        left = left_case / "constant" / "polyMesh" / name
        right = right_case / "constant" / "polyMesh" / name
        left_hash = _file_hash(left)
        right_hash = _file_hash(right)
        row_same = left_hash is not None and left_hash == right_hash
        rows.append(
            {
                "file": name,
                "same": row_same,
                "left_present": left_hash is not None,
                "right_present": right_hash is not None,
            },
        )
        same = same and row_same
    return {"same": same, "files": rows}


def _file_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _time_sort_key(value: str) -> tuple[int, float | str]:
    try:
        return (0, float(value))
    except ValueError:
        return (1, value)

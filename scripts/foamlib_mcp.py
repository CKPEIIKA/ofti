from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ofti.core.boundary import build_boundary_matrix
from ofti.foam import openfoam
from ofti.foamlib_adapter import available as foamlib_available
from ofti.foamlib_adapter import read_entry as foamlib_read_entry
from ofti.foamlib_adapter import write_entry as foamlib_write_entry


@dataclass
class MCPRequest:
    id: str | int | None
    method: str
    params: dict[str, Any]


def _is_case_dir(path: Path) -> bool:
    return (path / "system" / "controlDict").is_file()


def _list_cases(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    cases: list[str] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        if _is_case_dir(entry):
            cases.append(str(entry))
    return sorted(cases)


def _read_entry(params: dict[str, Any]) -> str:
    path = Path(params["path"]).expanduser()
    key = params["key"]
    if not foamlib_available():
        raise RuntimeError("foamlib not available")  # noqa: TRY003
    return foamlib_read_entry(path, key)


def _write_entry(params: dict[str, Any]) -> bool:
    path = Path(params["path"]).expanduser()
    key = params["key"]
    value = params["value"]
    if not foamlib_available():
        raise RuntimeError("foamlib not available")  # noqa: TRY003
    if foamlib_write_entry(path, key, str(value)):
        return True
    return openfoam.write_entry(path, key, str(value))


def _boundary_matrix(params: dict[str, Any]) -> dict[str, Any]:
    case_path = Path(params["case"]).expanduser()
    matrix = build_boundary_matrix(case_path)
    return {
        "fields": matrix.fields,
        "patches": matrix.patches,
        "patch_types": matrix.patch_types,
        "data": {
            patch: {
                field: {
                    "status": cell.status,
                    "type": cell.bc_type,
                    "value": cell.value,
                }
                for field, cell in row.items()
            }
            for patch, row in matrix.data.items()
        },
    }


def handle_request(payload: dict[str, Any]) -> dict[str, Any]:
    request = MCPRequest(
        id=payload.get("id"),
        method=payload.get("method", ""),
        params=payload.get("params", {}),
    )

    try:
        if request.method == "list_cases":
            root = Path(request.params.get("root", ".")).expanduser()
            result = _list_cases(root)
        elif request.method == "read_entry":
            result = _read_entry(request.params)
        elif request.method == "write_entry":
            result = _write_entry(request.params)
        elif request.method == "boundary_matrix":
            result = _boundary_matrix(request.params)
        else:
            raise ValueError(f"Unknown method: {request.method}")  # noqa: TRY003, TRY301
        return {"id": request.id, "result": result}  # noqa: TRY300
    except Exception as exc:
        return {"id": request.id, "error": str(exc)}


def main() -> int:
    if os.environ.get("OFTI_MCP_DEV") != "1":
        sys.stderr.write("ofti-foamlib-mcp is development-only. Set OFTI_MCP_DEV=1 to run.\n")
        return 2
    for line in sys.stdin:
        raw = line.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps({"id": None, "error": f"Invalid JSON: {exc}"}) + "\n")
            sys.stdout.flush()
            continue
        response = handle_request(payload)
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

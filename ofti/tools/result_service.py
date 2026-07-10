from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.core.result_archive import create_result_pack, extract_result_pack
from ofti.tools.case_source_service import require_case_dir


def pack_payload(
    case_dir: Path,
    output: Path,
    *,
    time_name: str = "latest",
    include_processors: bool = False,
) -> dict[str, Any]:
    case = require_case_dir(case_dir)
    archive = output.resolve()
    manifest = create_result_pack(
        case,
        archive,
        time_name=time_name,
        include_processors=include_processors,
    )
    return {"ok": True, "case": str(case), "archive": str(archive), "manifest": manifest}


def unpack_payload(archive: Path, destination: Path) -> dict[str, Any]:
    source = archive.resolve()
    target = destination.resolve()
    manifest = extract_result_pack(source, target)
    return {"ok": True, "archive": str(source), "destination": str(target), "manifest": manifest}

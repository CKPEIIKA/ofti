from __future__ import annotations

from pathlib import Path

from ofti.core.tool_dicts_service import DictCreationResult
from ofti.core.tool_dicts_service import ensure_dict as ensure_dict_core
from ofti.foam.subprocess_utils import run_trusted


def ensure_dict(
    case_path: Path,
    name: str,
    path: Path,
    helper_cmd: list[str] | None,
    *,
    generate: bool,
) -> DictCreationResult:
    return ensure_dict_core(
        case_path,
        name,
        path,
        helper_cmd,
        generate=generate,
        helper_runner=run_trusted,
    )

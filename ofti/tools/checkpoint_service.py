from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.core.checkpoint import checkpoint_health
from ofti.tools.case_source_service import require_case_dir


def checkpoint_payload(case_dir: Path, *, expected_processors: int | None = None) -> dict[str, Any]:
    case_path = require_case_dir(case_dir)
    health = checkpoint_health(case_path, expected_processors=expected_processors)
    return {
        "case": str(case_path),
        "ok": bool(health["complete_times"]),
        "common": True,
        **health,
    }

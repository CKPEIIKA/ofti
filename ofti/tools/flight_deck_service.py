from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.tools import knife_service


def flight_deck_payload(case_path: Path) -> dict[str, Any]:
    status = knife_service.status_payload(case_path, lightweight=True, tail_bytes=256 * 1024)
    current = knife_service.current_payload(case_path, live=True)
    criteria = knife_service.criteria_payload(case_path)
    return {
        "case": str(case_path),
        "status": status,
        "current": current,
        "criteria": criteria,
        "actions": [
            {"key": "s", "action": "safe stop", "risk": "low"},
            {"key": "p", "action": "pause tracked solver", "risk": "medium"},
            {"key": "u", "action": "resume tracked solver", "risk": "low"},
            {"key": "a", "action": "adopt untracked solver", "risk": "low"},
        ],
    }

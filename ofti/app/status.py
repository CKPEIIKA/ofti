from __future__ import annotations

import os

from ofti.app.state import AppState


def mode_status(state: AppState) -> str:
    if not state.no_foam:
        return ""
    wm_dir = os.environ.get("WM_PROJECT_DIR")
    suffix = f" ({wm_dir})" if wm_dir else ""
    reason = f" [{state.no_foam_reason}]" if state.no_foam_reason else ""
    return f"OpenFOAM env not found{suffix}{reason}"


def status_with_check(state: AppState, base: str) -> str:
    status = state.check_status_line()
    if not status:
        return base
    if not base:
        return status
    return f"{base} | {status}"

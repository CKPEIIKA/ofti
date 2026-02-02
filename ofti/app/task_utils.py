from __future__ import annotations

from ofti.app.state import AppState


def task_running(state: AppState, name: str) -> bool:
    task = state.tasks.get(name)
    if not task:
        return False
    if task.thread and task.thread.is_alive():
        return task.status in ("running", "cancelling")
    return False

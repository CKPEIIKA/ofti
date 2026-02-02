from __future__ import annotations

import time

from ofti.app.state import AppState
from ofti.foam.tasks import Task


def running_tasks_status(state: AppState) -> str | None:
    tasks = [
        task
        for task in state.tasks.list_tasks()
        if task.status in ("running", "cancelling")
    ]
    if not tasks:
        return None
    labels = []
    for task in tasks:
        label = "case analysis" if task.name == "case_meta" else task.name
        if task.message and task.name != "case_meta":
            label = f"{label}({task.message})"
        labels.append(label)
    return f"running: {', '.join(labels)}"


def recent_task_summary(state: AppState) -> str | None:
    now = time.time()
    recent: Task | None = None
    for task in state.tasks.list_tasks():
        if task.name in ("case_meta",):
            continue
        if task.finished_at is None:
            continue
        if now - task.finished_at > 5.0:
            continue
        if recent is None or (task.finished_at and task.finished_at > recent.finished_at):
            recent = task
    if recent is None:
        return None
    message = recent.message or ""
    if message:
        message = f"({message})"
    return f"last: {recent.name} {recent.status}{message}"

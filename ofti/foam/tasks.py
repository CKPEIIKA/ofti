from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class Task:
    name: str
    status: str = "pending"
    message: str | None = None
    thread: threading.Thread | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    started_at: float | None = None
    finished_at: float | None = None


class TaskRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, Task] = {}

    def get(self, name: str) -> Task | None:
        with self._lock:
            return self._tasks.get(name)

    def list_tasks(self) -> list[Task]:
        with self._lock:
            return list(self._tasks.values())

    def start(self, name: str, target: Callable[[Task], None], message: str | None = None) -> Task:
        with self._lock:
            task = self._tasks.get(name)
            if task and task.thread and task.thread.is_alive():
                return task
            task = Task(name=name, status="running", message=message)
            self._tasks[name] = task

        def runner() -> None:
            task.started_at = time.time()
            try:
                target(task)
                if task.status in ("running", "cancelling"):
                    task.status = "done"
            except KeyboardInterrupt:
                task.status = "canceled"
            except Exception as exc:
                task.status = "error"
                task.message = str(exc)
            finally:
                task.finished_at = time.time()

        thread = threading.Thread(target=runner, daemon=True)
        task.thread = thread
        thread.start()
        return task

    def cancel(self, name: str) -> bool:
        with self._lock:
            task = self._tasks.get(name)
            if not task:
                return False
            task.cancel.set()
            if task.status == "running":
                task.status = "cancelling"
            return True

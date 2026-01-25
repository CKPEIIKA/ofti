from ofti.foam.tasks import TaskRegistry


def test_task_registry_start_and_complete() -> None:
    registry = TaskRegistry()

    def worker(task):
        task.message = "ok"

    task = registry.start("demo", worker)
    assert task.name == "demo"
    assert task.thread is not None
    task.thread.join(timeout=1.0)
    assert task.status in {"done", "running"}


def test_task_registry_cancel_sets_flag() -> None:
    registry = TaskRegistry()

    def worker(task):
        while not task.cancel.is_set():
            pass

    task = registry.start("loop", worker)
    assert registry.cancel("loop") is True
    assert task.cancel.is_set() is True

from __future__ import annotations

import types
from pathlib import Path
from threading import Thread
from typing import cast

from ofti.app import task_utils
from ofti.app.state import AppState
from ofti.foam.tasks import Task
from ofti.tools import zero_ops


def test_task_running_checks_thread_status() -> None:
    state = AppState()
    state.tasks._tasks["solver"] = Task(
        name="solver",
        status="running",
        thread=cast(Thread, types.SimpleNamespace(is_alive=lambda: True)),
    )
    assert task_utils.task_running(state, "solver") is True

    state.tasks._tasks["solver"].status = "done"
    assert task_utils.task_running(state, "solver") is False
    assert task_utils.task_running(state, "missing") is False


def test_copy_zero_to_orig_success_and_missing(tmp_path: Path, monkeypatch) -> None:
    case = tmp_path / "case"
    case.mkdir()
    messages: list[str] = []
    monkeypatch.setattr(zero_ops, "_show_message", lambda _screen, text: messages.append(text))

    zero_ops.copy_zero_to_orig(object(), case)
    assert messages[-1] == "Source 0 directory is missing."

    (case / "0").mkdir()
    (case / "0" / "U").write_text("internalField uniform (0 0 0);\n")
    zero_ops.copy_zero_to_orig(object(), case)

    assert (case / "0.orig" / "U").is_file()
    assert messages[-1] == "Copied 0 to 0.orig successfully."

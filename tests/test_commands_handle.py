from pathlib import Path

from ofti.app.commands import CommandCallbacks, command_suggestions, handle_command
from ofti.app.state import AppState


class DummyCallbacks:
    def __init__(self) -> None:
        self.called = []

    def _record(self, name, *_args):
        self.called.append(name)

    def check_syntax(self, *_args):
        self._record("check")

    def tools_screen(self, *_args):
        self._record("tools")

    def diagnostics_screen(self, *_args):
        self._record("diag")

    def run_current_solver(self, *_args):
        self._record("run")

    def show_message(self, _stdscr, msg: str):
        self._record(f"msg:{msg}")

    def tasks_screen(self, *_args):
        self._record("tasks")

    def openfoam_env_screen(self, *_args):
        self._record("foamenv")

    def clone_case(self, _stdscr, _case_path, target):
        self._record(f"clone:{target}")

    def search_screen(self, *_args):
        self._record("search")


def _callbacks() -> tuple[CommandCallbacks, DummyCallbacks]:
    cb = DummyCallbacks()
    return CommandCallbacks(
        check_syntax=cb.check_syntax,
        tools_screen=cb.tools_screen,
        diagnostics_screen=cb.diagnostics_screen,
        run_current_solver=cb.run_current_solver,
        show_message=cb.show_message,
        tasks_screen=cb.tasks_screen,
        openfoam_env_screen=cb.openfoam_env_screen,
        clone_case=cb.clone_case,
        search_screen=cb.search_screen,
    ), cb


def test_command_suggestions_includes_tools(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ofti.app.commands.list_tool_commands", lambda _: ["toolA"])
    suggestions = command_suggestions(tmp_path)
    assert "tool toolA" in suggestions
    assert "run toolA" in suggestions


def test_handle_command_branches(monkeypatch, tmp_path: Path) -> None:
    cb, record = _callbacks()
    state = AppState()
    case_path = tmp_path

    monkeypatch.setattr("ofti.app.commands.list_tool_commands", lambda _: ["toolA"])
    monkeypatch.setattr("ofti.app.commands.run_tool_by_name", lambda *_: True)

    assert handle_command(None, case_path, state, "check", cb) == "handled"
    assert handle_command(None, case_path, state, "tools", cb) == "handled"
    assert handle_command(None, case_path, state, "diag", cb) == "handled"
    assert handle_command(None, case_path, state, "run", cb) == "handled"
    assert handle_command(None, case_path, state, "search", cb) == "handled"
    assert handle_command(None, case_path, state, "foamenv", cb) == "handled"
    assert handle_command(None, case_path, state, "clone mycase", cb) == "handled"
    assert handle_command(None, case_path, state, "tasks", cb) == "handled"
    assert handle_command(None, case_path, state, "tool toolA", cb) == "handled"
    assert handle_command(None, case_path, state, "help", cb) == "handled"

    assert "check" in record.called
    assert "tools" in record.called
    assert "diag" in record.called
    assert "run" in record.called
    assert "search" in record.called
    assert "foamenv" in record.called
    assert "clone:mycase" in record.called
    assert "tasks" in record.called


def test_handle_command_no_foam(monkeypatch, tmp_path: Path) -> None:
    cb, record = _callbacks()
    state = AppState(no_foam=True)
    case_path = tmp_path

    monkeypatch.setattr("ofti.app.commands.list_tool_commands", lambda _: [])
    monkeypatch.setattr("ofti.app.commands.ensure_environment", lambda: None)

    assert handle_command(None, case_path, state, "nofoam", cb) == "handled"
    assert "msg:Mode set to foam." in record.called


def test_handle_command_cancel(monkeypatch, tmp_path: Path) -> None:
    cb, record = _callbacks()
    state = AppState()
    case_path = tmp_path

    monkeypatch.setattr("ofti.app.commands.list_tool_commands", lambda _: [])
    assert handle_command(None, case_path, state, "cancel check", cb) == "handled"
    assert any("msg:No running task named check_syntax." in msg for msg in record.called)

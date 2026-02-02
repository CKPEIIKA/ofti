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

    def terminal(self, *_args):
        command = "" if not _args else (_args[-1] or "")
        self._record(f"terminal:{command}")

    def mesh_menu(self, *_args):
        self._record("mesh")

    def physics_menu(self, *_args):
        self._record("physics")

    def simulation_menu(self, *_args):
        self._record("simulation")

    def postprocessing_menu(self, *_args):
        self._record("post")

    def clean_menu(self, *_args):
        self._record("clean")

    def clean_all(self, *_args):
        self._record("clean_all")

    def config_menu(self, *_args):
        self._record("config")

    def config_editor(self, *_args):
        self._record("config_editor")

    def config_create(self, *_args):
        self._record("config_create")

    def config_search(self, *_args):
        self._record("config_search")

    def config_check(self, *_args):
        self._record("config_check")


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
        terminal=cb.terminal,
        mesh_menu=cb.mesh_menu,
        physics_menu=cb.physics_menu,
        simulation_menu=cb.simulation_menu,
        postprocessing_menu=cb.postprocessing_menu,
        clean_menu=cb.clean_menu,
        clean_all=cb.clean_all,
        config_menu=cb.config_menu,
        config_editor=cb.config_editor,
        config_create=cb.config_create,
        config_search=cb.config_search,
        config_check=cb.config_check,
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
    monkeypatch.setattr("ofti.app.commands.run_tool_by_name", lambda *_a, **_k: True)

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
    assert handle_command(None, case_path, state, "config-editor", cb) == "handled"
    assert handle_command(None, case_path, state, "config-create", cb) == "handled"
    assert handle_command(None, case_path, state, "config-search", cb) == "handled"
    assert handle_command(None, case_path, state, "config-check", cb) == "handled"
    assert handle_command(None, case_path, state, "clean-all", cb) == "handled"

    assert "check" in record.called
    assert "tools" in record.called
    assert "diag" in record.called
    assert "run" in record.called
    assert "search" in record.called
    assert "foamenv" in record.called
    assert "clone:mycase" in record.called
    assert "tasks" in record.called
    assert "config_editor" in record.called
    assert "config_create" in record.called
    assert "config_search" in record.called
    assert "config_check" in record.called
    assert "clean_all" in record.called


def test_handle_command_terminal(monkeypatch, tmp_path: Path) -> None:
    cb, record = _callbacks()
    state = AppState()
    case_path = tmp_path

    monkeypatch.setattr("ofti.app.commands.list_tool_commands", lambda _: [])
    assert handle_command(None, case_path, state, "term", cb) == "handled"
    assert handle_command(None, case_path, state, "terminal ls -l", cb) == "handled"
    assert handle_command(None, case_path, state, ":!echo hi", cb) == "handled"
    assert "terminal:" in record.called
    assert "terminal:ls -l" in record.called
    assert "terminal:echo hi" in record.called


def test_handle_command_cancel(monkeypatch, tmp_path: Path) -> None:
    cb, record = _callbacks()
    state = AppState()
    case_path = tmp_path

    monkeypatch.setattr("ofti.app.commands.list_tool_commands", lambda _: [])
    assert handle_command(None, case_path, state, "cancel check", cb) == "handled"
    assert any("msg:No running task named check_syntax." in msg for msg in record.called)

from __future__ import annotations

import curses
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from ofti.app.clean_menu import clean_all, clean_case_menu
from ofti.app.commands import CommandCallbacks, command_suggestions, handle_command
from ofti.app.config_templates import create_missing_config_screen
from ofti.app.helpers import (
    is_case_dir,
    prompt_command,
    select_case_directory,
    set_no_foam_mode,
    show_message,
)
from ofti.app.menus.config import config_menu
from ofti.app.menus.mesh import mesh_menu
from ofti.app.menus.physics import physics_menu
from ofti.app.menus.postprocessing import postprocessing_menu
from ofti.app.menus.simulation import simulation_menu
from ofti.app.screens import check as check_screen
from ofti.app.screens import editor as editor_screen
from ofti.app.screens import main as main_screen
from ofti.app.screens import search as search_screen
from ofti.app.state import AppState, Screen
from ofti.app.status import mode_status
from ofti.core.domain import Case
from ofti.foam.config import fzf_enabled, get_config
from ofti.foam.exceptions import QuitAppError
from ofti.foam.openfoam import OpenFOAMError, discover_case_files
from ofti.foam.openfoam_env import ensure_environment
from ofti.foamlib.adapter import available as foamlib_available
from ofti.tools.case_ops import clone_case
from ofti.tools.diagnostics import diagnostics_screen
from ofti.tools.menus import tools_screen
from ofti.tools.solver import run_current_solver_live
from ofti.ui.adapter import CursesAdapter
from ofti.ui.router import ScreenRouter
from ofti.ui_curses.entry_browser import BrowserCallbacks
from ofti.ui_curses.openfoam_env import openfoam_env_screen
from ofti.ui_curses.viewer import Viewer


def run_tui(case_dir: str, debug: bool = False) -> None:
    """
    Run the TUI on the given OpenFOAM case directory.
    """
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    if not foamlib_available():
        raise SystemExit("foamlib is required. Install it in the current environment.")

    # Always resolve the case path so that any paths
    # discovered later share the same root, which keeps
    # Path.relative_to calls safe.
    input_path = Path(case_dir).expanduser().resolve()
    start_path = input_path.parent if input_path.is_file() else input_path
    state = AppState()
    curses.wrapper(_main, start_path, debug, state)


def _main(stdscr: Any, case_path: Path, debug: bool, state: AppState) -> None:
    curses.start_color()
    cfg = get_config()
    fg = _color_from_name(cfg.colors.get("focus_fg", "black"), curses.COLOR_BLACK)
    bg = _color_from_name(cfg.colors.get("focus_bg", "cyan"), curses.COLOR_CYAN)
    curses.init_pair(1, fg, bg)
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(4, curses.COLOR_RED, curses.COLOR_BLACK)

    if not is_case_dir(case_path):
        selected = select_case_directory(stdscr, case_path)
        if selected is None:
            return
        case_path = selected

    os.environ["OFTI_CASE_PATH"] = str(case_path)

    try:
        ensure_environment()
    except OpenFOAMError as exc:
        set_no_foam_mode(state, True, str(exc))

    try:
        _main_loop(stdscr, case_path, state)
    except QuitAppError:
        return
    except KeyboardInterrupt:
        # Clean, user-initiated exit with restored terminal state.
        return
    except (OpenFOAMError, OSError, RuntimeError, ValueError) as exc:  # pragma: no cover
        if debug:
            # Re-raise to get a full traceback in debug mode.
            raise
        show_message(stdscr, f"Unexpected error: {exc}")


def _screen_check(stdscr: Any, case_path: Path, state: AppState) -> Screen:
    state.transition(Screen.CHECK, action="check")
    callbacks = _command_callbacks()
    check_screen.check_syntax_screen(
        stdscr,
        case_path,
        state,
        command_callbacks=callbacks,
    )
    return Screen.MAIN_MENU


def _screen_tools(stdscr: Any, case_path: Path, state: AppState) -> Screen:
    state.transition(Screen.TOOLS, action="tools")
    callbacks = _command_callbacks()
    tools_screen(
        stdscr,
        case_path,
        command_handler=lambda cmd: handle_command(stdscr, case_path, state, cmd, callbacks),
        command_suggestions=lambda: command_suggestions(case_path),
    )
    return Screen.MAIN_MENU


def _screen_diagnostics(stdscr: Any, case_path: Path, state: AppState) -> Screen:
    state.transition(Screen.DIAGNOSTICS, action="diagnostics")
    callbacks = _command_callbacks()
    diagnostics_screen(
        stdscr,
        case_path,
        command_handler=lambda cmd: handle_command(stdscr, case_path, state, cmd, callbacks),
        command_suggestions=lambda: command_suggestions(case_path),
    )
    return Screen.MAIN_MENU


def _screen_search(stdscr: Any, case_path: Path, state: AppState) -> Screen:
    state.transition(Screen.SEARCH, action="search")
    callbacks = _browser_callbacks()
    search_screen.global_search_screen(
        stdscr,
        case_path,
        state,
        browser_callbacks=callbacks,
    )
    return Screen.MAIN_MENU


def _screen_editor(stdscr: Any, case_path: Path, state: AppState) -> Screen:
    state.transition(Screen.EDITOR, action="editor")
    callbacks = _command_callbacks()
    editor_callbacks = _browser_callbacks()
    editor_screen.editor_screen(
        stdscr,
        case_path,
        state,
        command_callbacks=callbacks,
        browser_callbacks=editor_callbacks,
    )
    return Screen.MAIN_MENU


def _screen_main_menu(stdscr: Any, case_path: Path, state: AppState) -> Screen | None:
    callbacks = _command_callbacks()

    def editor_screen_wrapper(stdscr: Any, path: Path, app_state: AppState) -> None:
        editor_screen.editor_screen(
            stdscr,
            path,
            app_state,
            command_callbacks=callbacks,
            browser_callbacks=_browser_callbacks(),
        )

    def check_screen_wrapper(stdscr: Any, path: Path, app_state: AppState) -> None:
        check_screen.check_syntax_screen(
            stdscr,
            path,
            app_state,
            command_callbacks=callbacks,
        )

    def search_screen_wrapper(stdscr: Any, path: Path, app_state: AppState) -> None:
        search_screen.global_search_screen(
            stdscr,
            path,
            app_state,
            browser_callbacks=_browser_callbacks(),
        )

    return main_screen.main_menu_screen(
        stdscr,
        case_path,
        state,
        command_callbacks=callbacks,
        editor_screen=editor_screen_wrapper,
        check_syntax_screen=check_screen_wrapper,
        global_search_screen=search_screen_wrapper,
    )


def _main_loop(stdscr: Any, case_path: Path, state: AppState) -> None:
    foam_case = Case(root=case_path)
    sections = discover_case_files(foam_case.root)
    section_names = [name for name, files in sections.items() if files]
    if not section_names:
        stdscr.addstr("No OpenFOAM case files found.\n")
        stdscr.addstr("Press any key to exit.\n")
        stdscr.refresh()
        stdscr.getch()
        return

    adapter = CursesAdapter(stdscr)
    router = ScreenRouter(
        handlers={
            Screen.MAIN_MENU: _screen_main_menu,
            Screen.CHECK: _screen_check,
            Screen.TOOLS: _screen_tools,
            Screen.DIAGNOSTICS: _screen_diagnostics,
            Screen.SEARCH: _screen_search,
            Screen.EDITOR: _screen_editor,
        },
    )
    next_screen: Screen | None = Screen.MAIN_MENU
    while next_screen is not None:
        next_screen = router.dispatch(
            next_screen,
            adapter.stdscr,
            case_path,
            state,
        )


def _tasks_screen(stdscr: Any, state: AppState) -> None:
    tasks = state.tasks.list_tasks()
    if not tasks:
        show_message(stdscr, "No background tasks running.")
        return
    lines = ["Background tasks:"]
    for task in sorted(tasks, key=lambda item: item.name):
        message = f" - {task.message}" if task.message else ""
        lines.append(f"{task.name}: {task.status}{message}")
    lines.append("")
    lines.append("Use :cancel <task-name> to stop a task.")
    viewer = Viewer(stdscr, "\n".join(lines))
    viewer.display()


def _run_terminal(stdscr: Any, case_path: Path, command: str | None) -> None:
    curses.def_prog_mode()
    curses.endwin()
    env = os.environ.copy()
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)
    shell_cmd = command or ""
    try:
        if shell_cmd:
            subprocess.run(
                ["bash", "--noprofile", "--norc", "-c", shell_cmd],
                cwd=case_path,
                env=env,
            )
        else:
            shell = env.get("SHELL") or "bash"
            subprocess.run([shell], cwd=case_path, env=env)
    except KeyboardInterrupt:
        pass
    finally:
        curses.reset_prog_mode()
        stdscr.clear()
        stdscr.refresh()
        show_message(stdscr, "Returned from terminal.")



def _command_callbacks() -> CommandCallbacks:
    def editor_screen_wrapper(stdscr: Any, path: Path, app_state: AppState) -> None:
        editor_screen.editor_screen(
            stdscr,
            path,
            app_state,
            command_callbacks=_command_callbacks(),
            browser_callbacks=_browser_callbacks(),
        )

    def check_screen_wrapper(stdscr: Any, path: Path, app_state: AppState) -> None:
        check_screen.check_syntax_screen(
            stdscr,
            path,
            app_state,
            command_callbacks=_command_callbacks(),
        )

    def search_screen_wrapper(stdscr: Any, path: Path, app_state: AppState) -> None:
        search_screen.global_search_screen(
            stdscr,
            path,
            app_state,
            browser_callbacks=_browser_callbacks(),
        )

    def mesh_menu_wrapper(stdscr: Any, path: Path, app_state: AppState) -> None:
        callbacks = _command_callbacks()
        mesh_menu(
            stdscr,
            path,
            app_state,
            command_handler=lambda cmd: handle_command(stdscr, path, app_state, cmd, callbacks),
            command_suggestions=lambda: command_suggestions(path),
        )

    def physics_menu_wrapper(stdscr: Any, path: Path, app_state: AppState) -> None:
        callbacks = _command_callbacks()
        physics_menu(
            stdscr,
            path,
            app_state,
            editor_screen_wrapper,
            check_screen_wrapper,
            command_handler=lambda cmd: handle_command(stdscr, path, app_state, cmd, callbacks),
            command_suggestions=lambda: command_suggestions(path),
        )

    def simulation_menu_wrapper(stdscr: Any, path: Path, app_state: AppState) -> None:
        callbacks = _command_callbacks()
        simulation_menu(
            stdscr,
            path,
            app_state,
            command_handler=lambda cmd: handle_command(stdscr, path, app_state, cmd, callbacks),
            command_suggestions=lambda: command_suggestions(path),
        )

    def postprocessing_menu_wrapper(stdscr: Any, path: Path, app_state: AppState) -> None:
        callbacks = _command_callbacks()
        postprocessing_menu(
            stdscr,
            path,
            app_state,
            command_handler=lambda cmd: handle_command(stdscr, path, app_state, cmd, callbacks),
            command_suggestions=lambda: command_suggestions(path),
        )

    def clean_menu_wrapper(stdscr: Any, path: Path, app_state: AppState) -> None:
        callbacks = _command_callbacks()
        clean_case_menu(
            stdscr,
            path,
            app_state,
            command_handler=lambda cmd: handle_command(stdscr, path, app_state, cmd, callbacks),
            command_suggestions=lambda: command_suggestions(path),
        )

    def tools_menu_wrapper(stdscr: Any, path: Path, app_state: AppState) -> None:
        callbacks = _command_callbacks()
        tools_screen(
            stdscr,
            path,
            command_handler=lambda cmd: handle_command(stdscr, path, app_state, cmd, callbacks),
            command_suggestions=lambda: command_suggestions(path),
        )

    def diagnostics_menu_wrapper(stdscr: Any, path: Path, app_state: AppState) -> None:
        callbacks = _command_callbacks()
        diagnostics_screen(
            stdscr,
            path,
            command_handler=lambda cmd: handle_command(stdscr, path, app_state, cmd, callbacks),
            command_suggestions=lambda: command_suggestions(path),
        )

    def config_menu_wrapper(stdscr: Any, path: Path, app_state: AppState) -> None:
        has_fzf = fzf_enabled()
        callbacks = _command_callbacks()
        config_menu(
            stdscr,
            path,
            app_state,
            has_fzf,
            editor_screen_wrapper,
            check_screen_wrapper,
            openfoam_env_screen,
            search_screen_wrapper,
            command_handler=lambda cmd: handle_command(stdscr, path, app_state, cmd, callbacks),
            command_suggestions=lambda: command_suggestions(path),
        )

    return CommandCallbacks(
        check_syntax=lambda stdscr, path, state: check_screen.check_syntax_screen(
            stdscr,
            path,
            state,
            command_callbacks=_command_callbacks(),
        ),
        tools_screen=tools_menu_wrapper,
        diagnostics_screen=diagnostics_menu_wrapper,
        run_current_solver=run_current_solver_live,
        show_message=show_message,
        tasks_screen=_tasks_screen,
        openfoam_env_screen=openfoam_env_screen,
        clone_case=clone_case,
        search_screen=search_screen_wrapper,
        terminal=_run_terminal,
        mesh_menu=mesh_menu_wrapper,
        physics_menu=physics_menu_wrapper,
        simulation_menu=simulation_menu_wrapper,
        postprocessing_menu=postprocessing_menu_wrapper,
        clean_menu=clean_menu_wrapper,
        clean_all=clean_all,
        config_menu=config_menu_wrapper,
        config_editor=editor_screen_wrapper,
        config_create=create_missing_config_screen,
        config_search=search_screen_wrapper,
        config_check=check_screen_wrapper,
    )


def _browser_callbacks() -> BrowserCallbacks:
    cmd_callbacks = _command_callbacks()

    def handle_cmd(stdscr: Any, path: Path, app_state: AppState, cmd: str) -> str | None:
        return handle_command(stdscr, path, app_state, cmd, cmd_callbacks)

    return BrowserCallbacks(
        show_message=show_message,
        view_file=editor_screen.view_file_screen,
        prompt_command=prompt_command,
        command_suggestions=command_suggestions,
        handle_command=handle_cmd,
        mode_status=mode_status,
    )


def _color_from_name(value: str, default: int) -> int:
    mapping = {
        "black": curses.COLOR_BLACK,
        "red": curses.COLOR_RED,
        "green": curses.COLOR_GREEN,
        "yellow": curses.COLOR_YELLOW,
        "blue": curses.COLOR_BLUE,
        "magenta": curses.COLOR_MAGENTA,
        "cyan": curses.COLOR_CYAN,
        "white": curses.COLOR_WHITE,
    }
    return mapping.get(value.strip().lower(), default)

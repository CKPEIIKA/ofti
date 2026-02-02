from __future__ import annotations

import curses
import os
import subprocess
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from ofti.foam.config import fzf_enabled, get_config, key_in
from ofti.foam.exceptions import QuitAppError
from ofti.foam.subprocess_utils import resolve_executable, run_trusted
from ofti.ui_curses.help.manager import help_registry
from ofti.ui_curses.viewer import Viewer


def _show_help(stdscr: Any, title: str, lines: list[str]) -> None:
    text = "\n".join([title, "", *lines])
    Viewer(stdscr, text).display()


def _default_hint_provider(has_command: bool) -> Callable[[int], str]:
    def hint(_idx: int) -> str:
        parts = ["Enter: select", "h/esc: back", "?: help", "! term"]
        if has_command:
            parts.append(": cmd")
        if fzf_enabled():
            parts.append("/ search")
        return " | ".join(parts)

    return hint


def _prompt_command(stdscr: Any, suggestions: list[str] | None) -> str:  # noqa: C901, PLR0912
    height, width = stdscr.getmaxyx()
    buffer: list[str] = []
    cursor = 0
    last_matches: list[str] = []
    match_index = 0
    last_buffer = ""

    def render() -> None:
        try:
            stdscr.move(height - 1, 0)
            stdscr.clrtoeol()
            display = ":" + "".join(buffer)
            stdscr.addstr(height - 1, 0, display[: max(1, width - 1)])
            stdscr.move(height - 1, min(width - 1, 1 + cursor))
            stdscr.refresh()
        except curses.error:
            pass

    render()
    while True:
        key = stdscr.getch()

        if key in (curses.KEY_ENTER, 10, 13):
            return "".join(buffer).strip()
        if key in (27,):  # ESC
            return ""
        if key in (curses.KEY_BACKSPACE, 127, 8):
            if cursor > 0:
                buffer.pop(cursor - 1)
                cursor -= 1
            render()
            continue
        if key == curses.KEY_LEFT:
            if cursor > 0:
                cursor -= 1
            render()
            continue
        if key == curses.KEY_RIGHT:
            if cursor < len(buffer):
                cursor += 1
            render()
            continue
        if key == 9:  # TAB
            pool = suggestions or []
            current = "".join(buffer)
            if current != last_buffer:
                last_matches = [s for s in pool if s.startswith(current)]
                match_index = 0
                last_buffer = current
            if last_matches:
                completion = last_matches[match_index % len(last_matches)]
                buffer = list(completion)
                cursor = len(buffer)
                match_index += 1
                render()
            continue
        if 32 <= key <= 126:
            buffer.insert(cursor, chr(key))
            cursor += 1
            render()



def _fzf_pick_option(stdscr: Any, options: list[str]) -> int | None:
    """
    Use fzf to pick an option from the given list.

    Returns the selected index, or None if selection was cancelled or
    fzf is unavailable.
    """
    if not options or not fzf_enabled():
        return None

    fzf_input = "\n".join(options)

    curses.def_prog_mode()
    curses.endwin()
    try:
        resolved = resolve_executable("fzf")
        result = run_trusted(
            [resolved],
            stdin=fzf_input,
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        curses.reset_prog_mode()
        stdscr.clear()
        stdscr.refresh()

    if result.returncode != 0:
        return None

    selected = result.stdout.strip()
    if not selected:
        return None

    try:
        return options.index(selected)
    except ValueError:
        return None


class Menu:
    def __init__(
        self,
        stdscr: Any,
        title: str,
        options: list[str],
        extra_lines: list[str] | None = None,
        banner_lines: list[str] | None = None,
        banner_provider: Callable[[], list[str]] | None = None,
        initial_index: int | None = None,
        command_handler: Callable[[str], str | None] | None = None,
        command_suggestions: Callable[[], list[str]] | None = None,
        hint_provider: Callable[[int], str | None] | None = None,
        status_line: str | None = None,
        disabled_indices: set[int] | None = None,
        help_lines: list[str] | None = None,
        disabled_reasons: dict[int, str] | None = None,
        disabled_helpers: dict[int, str] | None = None,
    ) -> None:
        self.stdscr = stdscr
        self.title = title
        self.options = options
        if options:
            start_index = 0 if initial_index is None else initial_index
            self.current_option = max(0, min(start_index, len(options) - 1))
        else:
            self.current_option = 0
        self.extra_lines = extra_lines or []
        self.banner_lines = banner_lines or ["=== OFTI ==="]
        self.banner_provider = banner_provider
        self.command_handler = command_handler
        self.command_suggestions = command_suggestions
        self.hint_provider = hint_provider or _default_hint_provider(
            command_handler is not None,
        )
        self.status_line = status_line
        self.disabled_indices = disabled_indices or set()
        self.disabled_reasons = disabled_reasons or {}
        self.disabled_helpers = disabled_helpers or {}
        self.help_lines = help_lines or []
        self._scroll = 0

    def display(self) -> None:  # noqa: C901, PLR0912
        if hasattr(self.stdscr, "erase"):
            self.stdscr.erase()
        else:
            self.stdscr.clear()
        height, width = self.stdscr.getmaxyx()
        row = 0
        show_status = self.hint_provider is not None or self.status_line is not None

        if self.banner_provider is not None:
            self.banner_lines = self.banner_provider()

        # Header
        try:
            for line in self.banner_lines:
                if row >= height:
                    break
                self.stdscr.addstr(row, 0, line[: max(1, width - 1)])
                row += 1
            if row < height:
                row += 1
            if row < height:
                self.stdscr.addstr(row, 0, self.title[: max(1, width - 1)])
                row += 1
            if row < height:
                row += 1
            for line in self.extra_lines:
                if row >= height:
                    break
                self.stdscr.addstr(row, 0, line[: max(1, width - 1)])
                row += 1
            if self.extra_lines and row < height:
                row += 1
        except curses.error:
            # Ignore drawing errors on very small terminals.
            pass

        # Options
        available = max(0, height - row - (1 if show_status else 0))
        if available > 0:
            if self.current_option < self._scroll:
                self._scroll = self.current_option
            elif self.current_option >= self._scroll + available:
                self._scroll = self.current_option - available + 1

            max_scroll = max(0, len(self.options) - available)
            self._scroll = min(self._scroll, max_scroll)

            for idx in range(self._scroll, min(len(self.options), self._scroll + available)):
                prefix = "  >> " if idx == self.current_option else "     "
                max_label_len = max(1, width - 1 - len(prefix))
                label = self.options[idx][:max_label_len]
                line = f"{prefix}{label}"
                try:
                    if idx == self.current_option and idx not in self.disabled_indices:
                        self.stdscr.attron(curses.color_pair(1))
                        self.stdscr.addstr(row, 0, line[: max(1, width - 1)])
                        self.stdscr.attroff(curses.color_pair(1))
                    elif idx in self.disabled_indices:
                        self.stdscr.attron(curses.A_DIM)
                        self.stdscr.addstr(row, 0, line[: max(1, width - 1)])
                        self.stdscr.attroff(curses.A_DIM)
                    else:
                        self.stdscr.addstr(row, 0, line[: max(1, width - 1)])
                except curses.error:
                    break
                row += 1

        if show_status:
            hint = self.hint_provider(self.current_option) if self.hint_provider else ""
            hint = hint or ""
            if self.status_line:
                hint = f"{self.status_line} | {hint}" if hint else self.status_line
            try:
                self.stdscr.attron(curses.A_REVERSE)
                self.stdscr.addstr(
                    height - 1,
                    0,
                    hint[: max(1, width - 1)].ljust(max(1, width - 1)),
                )
                self.stdscr.attroff(curses.A_REVERSE)
            except curses.error:
                pass

        try:
            if hasattr(self.stdscr, "noutrefresh"):
                self.stdscr.noutrefresh()
                curses.doupdate()
            else:
                self.stdscr.refresh()
        except curses.error:
            self.stdscr.refresh()

    def _show_disabled_info(self, idx: int) -> None:
        lines: list[str] = []
        reason = self.disabled_reasons.get(idx)
        if reason:
            lines.append(reason)
        helper = self.disabled_helpers.get(idx)
        helper_lines = help_registry.context(helper) if helper else []
        if helper_lines:
            if lines:
                lines.append("")
            lines.append("Suggested action:")
            lines.extend(helper_lines)
        if not lines:
            lines = ["This option is currently unavailable."]
        _show_help(self.stdscr, "Option unavailable", lines)


    def _run_terminal_fallback(self) -> None:
        case_path = os.environ.get("OFTI_CASE_PATH") or str(Path.cwd())
        curses.def_prog_mode()
        curses.endwin()
        env = os.environ.copy()
        env.pop("BASH_ENV", None)
        env.pop("ENV", None)
        try:
            shell = env.get("SHELL") or "bash"
            subprocess.run([shell], cwd=case_path, env=env)  # noqa: S603
        except KeyboardInterrupt:
            pass
        finally:
            curses.reset_prog_mode()
            self.stdscr.clear()
            self.stdscr.refresh()


    def _help_lines(self) -> list[str]:
        lines = [
            f"Page: {self.title}",
            f"Options: {len(self.options)}",
            "",
            "Controls:",
            "  j/k or arrows  : move up/down",
            "  g/G            : jump to top/bottom",
            "  l or Enter     : select",
        ]
        if isinstance(self, RootMenu):
            lines.append("  q              : quit")
        else:
            lines.append("  h or q          : go back")
        lines.append("  !              : terminal")
        if self.command_handler is not None:
            lines.append("  :              : command line (Tab completes)")
        if fzf_enabled():
            lines.append("  /              : search (fzf)")
            lines.append("  s              : config search")
        lines.append("  ?              : this help")
        lines.append("")
        lines.append("Commands:")
        lines.append("  :check  :tools  :diag  :run  :tasks  :clean-all")
        lines.append("  :foamenv  :clone  :tool <name>  :cancel <name>  :quit")
        lines.append("  :config-editor  :config-create  :config-search  :config-check")
        if self.help_lines:
            lines.append("")
            lines.append("About:")
            lines.extend(self.help_lines)
        return lines

    def _show_help(self) -> None:
        _show_help(self.stdscr, "Help", self._help_lines())

    def _handle_navigation_key(self, key: int, cfg: Any) -> str | None:  # noqa: C901, PLR0911
        if key in (curses.KEY_UP,) or key_in(key, cfg.keys.get("up", [])):
            self.current_option = (self.current_option - 1) % len(self.options)
            return "continue"
        if key in (curses.KEY_DOWN,) or key_in(key, cfg.keys.get("down", [])):
            self.current_option = (self.current_option + 1) % len(self.options)
            return "continue"
        if key_in(key, cfg.keys.get("top", [])):
            self.current_option = 0
            return "continue"
        if key_in(key, cfg.keys.get("bottom", [])):
            self.current_option = len(self.options) - 1
            return "continue"
        if key_in(key, cfg.keys.get("command", [])):
            return "command"
        if key == ord("!"):
            return "terminal"
        if key_in(key, cfg.keys.get("search", [])):
            return "search"
        if key_in(key, cfg.keys.get("global_search", [])):
            return "global_search"
        if key == curses.KEY_RESIZE:
            return "continue"
        if key_in(key, cfg.keys.get("help", [])):
            self._show_help()
            return "continue"
        if key in (curses.KEY_ENTER,) or key_in(key, cfg.keys.get("select", [])):
            return "select"
        if key_in(key, cfg.keys.get("back", [])):
            return "back"
        return None

    def navigate(self) -> int:  # noqa: C901, PLR0912
        cfg = get_config()
        while True:
            self.display()
            key = self.stdscr.getch()

            if key_in(key, cfg.keys.get("quit", [])):
                raise QuitAppError()

            action = self._handle_navigation_key(key, cfg)
            if action == "command":
                if self.command_handler is None:
                    continue
                suggestions = self.command_suggestions() if self.command_suggestions else None
                command = _prompt_command(self.stdscr, suggestions)
                if not command:
                    continue
                result = self.command_handler(command)
                if result == "quit":
                    return -1
                continue
            if action == "terminal":
                if self.command_handler is not None:
                    result = self.command_handler("term")
                    if result == "quit":
                        return -1
                else:
                    self._run_terminal_fallback()
                continue
            if action == "global_search":
                if self.command_handler is not None:
                    result = self.command_handler("search")
                    if result == "quit":
                        return -1
                continue
            if action == "search":
                idx = _fzf_pick_option(self.stdscr, self.options)
                if idx is not None:
                    self.current_option = idx
                continue
            if action == "select":
                if self.current_option == len(self.options) - 1:
                    return -1
                if self.current_option in self.disabled_indices:
                    with suppress(curses.error):
                        curses.beep()
                    self._show_disabled_info(self.current_option)
                    continue
                return self.current_option
            if action == "back":
                return -1
            if action == "continue":
                continue


class Submenu(Menu):
    def __init__(
        self,
        stdscr: Any,
        title: str,
        options: list[str],
        command_handler: Callable[[str], str | None] | None = None,
        command_suggestions: Callable[[], list[str]] | None = None,
        hint_provider: Callable[[int], str | None] | None = None,
        status_line: str | None = None,
        disabled_indices: set[int] | None = None,
        help_lines: list[str] | None = None,
        disabled_reasons: dict[int, str] | None = None,
        disabled_helpers: dict[int, str] | None = None,
    ) -> None:
        super().__init__(
            stdscr,
            title,
            [*options, "Go back"],
            command_handler=command_handler,
            command_suggestions=command_suggestions,
            hint_provider=hint_provider,
            status_line=status_line,
            disabled_indices=disabled_indices,
            help_lines=help_lines,
            disabled_reasons=disabled_reasons,
            disabled_helpers=disabled_helpers,
        )

    def navigate(self) -> int:  # noqa: C901, PLR0912
        cfg = get_config()
        while True:
            self.display()
            key = self.stdscr.getch()

            if key_in(key, cfg.keys.get("quit", [])):
                raise QuitAppError()
            action = self._handle_navigation_key(key, cfg)
            if action == "command":
                if self.command_handler is None:
                    continue
                suggestions = self.command_suggestions() if self.command_suggestions else None
                command = _prompt_command(self.stdscr, suggestions)
                if not command:
                    continue
                result = self.command_handler(command)
                if result == "quit":
                    return -1
                continue
            if action == "terminal":
                if self.command_handler is not None:
                    result = self.command_handler("term")
                    if result == "quit":
                        return -1
                else:
                    self._run_terminal_fallback()
                continue
            if action == "global_search":
                if self.command_handler is not None:
                    result = self.command_handler("search")
                    if result == "quit":
                        return -1
                continue
            if action == "search":
                idx = _fzf_pick_option(self.stdscr, self.options)
                if idx is not None:
                    self.current_option = idx
                continue
            if action == "select":
                if self.current_option == len(self.options) - 1:
                    return -1
                if self.current_option in self.disabled_indices:
                    with suppress(curses.error):
                        curses.beep()
                    self._show_disabled_info(self.current_option)
                    continue
                return self.current_option
            if action == "back":
                return -1
            if action == "continue":
                continue


class RootMenu(Menu):
    """
    Root-level menu where 'q' quits the program but 'h' does not.
    """

    def __init__(
        self,
        stdscr: Any,
        title: str,
        options: list[str],
        extra_lines: list[str] | None = None,
        banner_lines: list[str] | None = None,
        banner_provider: Callable[[], list[str]] | None = None,
        initial_index: int | None = None,
        command_handler: Callable[[str], str | None] | None = None,
        command_suggestions: Callable[[], list[str]] | None = None,
        hint_provider: Callable[[int], str | None] | None = None,
        status_line: str | None = None,
        disabled_indices: set[int] | None = None,
        disabled_reasons: dict[int, str] | None = None,
        disabled_helpers: dict[int, str] | None = None,
        help_lines: list[str] | None = None,
    ) -> None:
        super().__init__(
            stdscr,
            title,
            options,
            extra_lines=extra_lines,
            banner_lines=banner_lines,
            banner_provider=banner_provider,
            initial_index=initial_index,
            command_handler=command_handler,
            command_suggestions=command_suggestions,
            hint_provider=hint_provider,
            status_line=status_line,
            disabled_indices=disabled_indices,
            disabled_reasons=disabled_reasons,
            disabled_helpers=disabled_helpers,
            help_lines=help_lines,
        )

    def navigate(self) -> int:  # noqa: C901, PLR0912
        cfg = get_config()
        while True:
            self.display()
            key = self.stdscr.getch()

            if key_in(key, cfg.keys.get("quit", [])):
                raise QuitAppError()
            action = self._handle_navigation_key(key, cfg)
            if action == "command":
                if self.command_handler is None:
                    continue
                suggestions = self.command_suggestions() if self.command_suggestions else None
                command = _prompt_command(self.stdscr, suggestions)
                if not command:
                    continue
                result = self.command_handler(command)
                if result == "quit":
                    return -1
                continue
            if action == "terminal":
                if self.command_handler is not None:
                    result = self.command_handler("term")
                    if result == "quit":
                        return -1
                else:
                    self._run_terminal_fallback()
                continue
            if action == "global_search":
                if self.command_handler is not None:
                    result = self.command_handler("search")
                    if result == "quit":
                        return -1
                continue
            if action == "search":
                idx = _fzf_pick_option(self.stdscr, self.options)
                if idx is not None:
                    self.current_option = idx
                continue
            if action == "select":
                if self.current_option == len(self.options) - 1:
                    return -1
                if self.current_option in self.disabled_indices:
                    with suppress(curses.error):
                        curses.beep()
                    self._show_disabled_info(self.current_option)
                    continue
                return self.current_option
            if action == "back":
                return -1
            if action == "continue":
                continue

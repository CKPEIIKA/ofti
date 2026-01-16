from __future__ import annotations

import curses
import subprocess
from typing import List, Any, Callable, Optional

from .config import get_config, key_in, fzf_enabled


def _show_help(stdscr: Any) -> None:
    stdscr.clear()
    stdscr.addstr("of_tui help\n\n")
    stdscr.addstr("Navigation:\n")
    stdscr.addstr("  j / k or arrows : move up/down\n")
    stdscr.addstr("  g / G           : jump to top/bottom\n")
    stdscr.addstr("  l or Enter      : select\n")
    stdscr.addstr("  h or q          : go back (use :quit on root)\n")
    stdscr.addstr("  :               : command line (Tab completes)\n")
    stdscr.addstr("  /               : search (fzf)\n")
    stdscr.addstr("  ?               : show this help\n\n")
    stdscr.addstr("Commands:\n")
    stdscr.addstr("  :check  :tools  :diag  :run  :nofoam  :tool <name>  :quit\n\n")
    stdscr.addstr("Press any key to return.\n")
    stdscr.refresh()
    stdscr.getch()


def _prompt_command(stdscr: Any, suggestions: Optional[List[str]]) -> str:
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



def _fzf_pick_option(stdscr: Any, options: List[str]) -> Optional[int]:
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
        result = subprocess.run(
            ["fzf"],
            input=fzf_input,
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
        options: List[str],
        extra_lines: Optional[List[str]] = None,
        banner_lines: Optional[List[str]] = None,
        command_handler: Optional[Callable[[str], Optional[str]]] = None,
        command_suggestions: Optional[Callable[[], List[str]]] = None,
        hint_provider: Optional[Callable[[int], Optional[str]]] = None,
    ) -> None:
        self.stdscr = stdscr
        self.title = title
        self.options = options
        self.current_option = 0
        self.extra_lines = extra_lines or []
        self.banner_lines = banner_lines or ["=== Config Editor ==="]
        self.command_handler = command_handler
        self.command_suggestions = command_suggestions
        self.hint_provider = hint_provider
        self._scroll = 0

    def display(self) -> None:
        self.stdscr.clear()
        height, width = self.stdscr.getmaxyx()
        row = 0
        show_status = self.hint_provider is not None

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
            if self._scroll > max_scroll:
                self._scroll = max_scroll

            for idx in range(self._scroll, min(len(self.options), self._scroll + available)):
                prefix = "  >> " if idx == self.current_option else "     "
                max_label_len = max(1, width - 1 - len(prefix))
                label = self.options[idx][:max_label_len]
                line = f"{prefix}{label}"
                try:
                    if idx == self.current_option:
                        self.stdscr.attron(curses.color_pair(1))
                        self.stdscr.addstr(row, 0, line[: max(1, width - 1)])
                        self.stdscr.attroff(curses.color_pair(1))
                    else:
                        self.stdscr.addstr(row, 0, line[: max(1, width - 1)])
                except curses.error:
                    break
                row += 1

        if show_status and self.hint_provider is not None:
            hint = self.hint_provider(self.current_option) or ""
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

        self.stdscr.refresh()

    def _handle_navigation_key(self, key: int, cfg: Any) -> Optional[str]:
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
        if key_in(key, cfg.keys.get("search", [])):
            return "search"
        if key == curses.KEY_RESIZE:
            return "continue"
        if key_in(key, cfg.keys.get("help", [])):
            _show_help(self.stdscr)
            return "continue"
        if key in (curses.KEY_ENTER,) or key_in(key, cfg.keys.get("select", [])):
            return "select"
        if key_in(key, cfg.keys.get("back", [])):
            return "back"
        return None

    def navigate(self) -> int:
        cfg = get_config()
        while True:
            self.display()
            key = self.stdscr.getch()

            if key == ord("q"):
                return -1

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
            if action == "search":
                idx = _fzf_pick_option(self.stdscr, self.options)
                if idx is not None:
                    self.current_option = idx
                continue
            if action == "select":
                return self.current_option
            if action == "back":
                return -1
            if action == "continue":
                continue
            if key == ord("q"):
                return -1


class Submenu(Menu):
    def __init__(
        self,
        stdscr: Any,
        title: str,
        options: List[str],
        command_handler: Optional[Callable[[str], Optional[str]]] = None,
        command_suggestions: Optional[Callable[[], List[str]]] = None,
        hint_provider: Optional[Callable[[int], Optional[str]]] = None,
    ) -> None:
        super().__init__(
            stdscr,
            title,
            options + ["Go back"],
            command_handler=command_handler,
            command_suggestions=command_suggestions,
            hint_provider=hint_provider,
        )

    def navigate(self) -> int:
        cfg = get_config()
        while True:
            self.display()
            key = self.stdscr.getch()

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
            if action == "search":
                idx = _fzf_pick_option(self.stdscr, self.options)
                if idx is not None:
                    self.current_option = idx
                continue
            if action == "select":
                if self.current_option == len(self.options) - 1:
                    return -1
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
        options: List[str],
        extra_lines: Optional[List[str]] = None,
        banner_lines: Optional[List[str]] = None,
        command_handler: Optional[Callable[[str], Optional[str]]] = None,
        command_suggestions: Optional[Callable[[], List[str]]] = None,
        hint_provider: Optional[Callable[[int], Optional[str]]] = None,
    ) -> None:
        super().__init__(
            stdscr,
            title,
            options,
            extra_lines=extra_lines,
            banner_lines=banner_lines,
            command_handler=command_handler,
            command_suggestions=command_suggestions,
            hint_provider=hint_provider,
        )

    def navigate(self) -> int:
        cfg = get_config()
        while True:
            self.display()
            key = self.stdscr.getch()

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
            if action == "search":
                idx = _fzf_pick_option(self.stdscr, self.options)
                if idx is not None:
                    self.current_option = idx
                continue
            if action == "select":
                return self.current_option
            if action == "back":
                return -1
            if action == "continue":
                continue

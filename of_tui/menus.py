import curses
import shutil
import subprocess
from typing import List, Any


def _show_help(stdscr: Any) -> None:
    stdscr.clear()
    stdscr.addstr("of_tui help\n\n")
    stdscr.addstr("Navigation:\n")
    stdscr.addstr("  j / k or arrows : move up/down\n")
    stdscr.addstr("  l or Enter      : select\n")
    stdscr.addstr("  h or q          : go back / quit\n")
    stdscr.addstr("  ?               : show this help\n\n")
    stdscr.addstr("Press any key to return.\n")
    stdscr.refresh()
    stdscr.getch()


def _fzf_pick_option(stdscr: Any, options: List[str]) -> int | None:
    """
    Use fzf to pick an option from the given list.

    Returns the selected index, or None if selection was cancelled or
    fzf is unavailable.
    """
    if not options or shutil.which("fzf") is None:
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
        extra_lines: List[str] | None = None,
        banner_lines: List[str] | None = None,
    ) -> None:
        self.stdscr = stdscr
        self.title = title
        self.options = options
        self.current_option = 0
        self.extra_lines = extra_lines or []
        self.banner_lines = banner_lines or ["=== OpenFOAM Config Editor ==="]

    def display(self) -> None:
        self.stdscr.clear()
        height, width = self.stdscr.getmaxyx()

        # Header
        try:
            for line in self.banner_lines:
                self.stdscr.addstr(line[: max(1, width - 1)] + "\n")
            self.stdscr.addstr("\n")
            self.stdscr.addstr((self.title[: max(1, width - 1)]) + "\n\n")
            for line in self.extra_lines:
                self.stdscr.addstr(line[: max(1, width - 1)] + "\n")
            if self.extra_lines:
                self.stdscr.addstr("\n")
        except curses.error:
            # Ignore drawing errors on very small terminals.
            pass

        # Options
        for index, option in enumerate(self.options):
            prefix = "  >> " if index == self.current_option else "     "
            max_label_len = max(1, width - 1 - len(prefix))
            label = option[:max_label_len]
            line = f"{prefix}{label}"
            try:
                if index == self.current_option:
                    self.stdscr.attron(curses.color_pair(1))
                    self.stdscr.addstr(line + "\n")
                    self.stdscr.attroff(curses.color_pair(1))
                else:
                    self.stdscr.addstr(line + "\n")
            except curses.error:
                # If the terminal is too small, just stop drawing more lines.
                break

        self.stdscr.refresh()

    def navigate(self) -> int:
        while True:
            self.display()
            key = self.stdscr.getch()

            if key in (ord("k"), curses.KEY_UP):
                self.current_option = (self.current_option - 1) % len(self.options)
            elif key in (ord("j"), curses.KEY_DOWN):
                self.current_option = (self.current_option + 1) % len(self.options)
            elif key == ord("/"):
                idx = _fzf_pick_option(self.stdscr, self.options)
                if idx is not None:
                    self.current_option = idx
                continue
            elif key == curses.KEY_RESIZE:
                # Terminal resized; just redraw.
                continue
            elif key == ord("?"):
                _show_help(self.stdscr)
                continue
            elif key in (ord("\n"), curses.KEY_ENTER, ord("l")):
                return self.current_option
            elif key in (ord("q"), ord("h")):
                return -1


class Submenu(Menu):
    def __init__(self, stdscr: Any, title: str, options: List[str]) -> None:
        super().__init__(stdscr, title, options + ["Go back"])

    def navigate(self) -> int:
        while True:
            self.display()
            key = self.stdscr.getch()

            if key in (ord("k"), curses.KEY_UP):
                self.current_option = (self.current_option - 1) % len(self.options)
            elif key in (ord("j"), curses.KEY_DOWN):
                self.current_option = (self.current_option + 1) % len(self.options)
            elif key == ord("/"):
                idx = _fzf_pick_option(self.stdscr, self.options)
                if idx is not None:
                    self.current_option = idx
                continue
            elif key == curses.KEY_RESIZE:
                # Terminal resized; just redraw.
                continue
            elif key == ord("?"):
                _show_help(self.stdscr)
                continue
            elif key in (ord("\n"), curses.KEY_ENTER, ord("l")):
                if self.current_option == len(self.options) - 1:
                    return -1
                return self.current_option
            elif key in (ord("q"), ord("h")):
                return -1


class RootMenu(Menu):
    """
    Root-level menu where 'q' quits the program but 'h' does not.
    """

    def __init__(
        self,
        stdscr: Any,
        title: str,
        options: List[str],
        extra_lines: List[str] | None = None,
        banner_lines: List[str] | None = None,
    ) -> None:
        super().__init__(stdscr, title, options, extra_lines=extra_lines, banner_lines=banner_lines)

    def navigate(self) -> int:
        while True:
            self.display()
            key = self.stdscr.getch()

            if key in (ord("k"), curses.KEY_UP):
                self.current_option = (self.current_option - 1) % len(self.options)
            elif key in (ord("j"), curses.KEY_DOWN):
                self.current_option = (self.current_option + 1) % len(self.options)
            elif key == ord("/"):
                idx = _fzf_pick_option(self.stdscr, self.options)
                if idx is not None:
                    self.current_option = idx
                continue
            elif key == ord("?"):
                _show_help(self.stdscr)
                continue
            elif key == curses.KEY_RESIZE:
                continue
            elif key in (ord("\n"), curses.KEY_ENTER, ord("l")):
                return self.current_option
            elif key == ord("q"):
                return -1
            elif key == ord("h"):
                # Ignore 'h' on the root menu so it does not quit.
                continue

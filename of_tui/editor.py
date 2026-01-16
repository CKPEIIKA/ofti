from __future__ import annotations

import curses
import os
import subprocess
from curses import textpad
from dataclasses import dataclass
from typing import Callable, List, Optional, Any

from .config import get_config, key_in


def autoformat_value(value: str) -> str:
    """
    Apply a very small amount of auto-formatting before saving.

    - For single-line values, trim leading/trailing whitespace.
    - For multi-line values, leave content as-is (only strip trailing
      newlines) to avoid breaking complex dictionaries.
    """
    text = value.rstrip("\n")
    if "\n" in text:
        return text
    return text.strip()


@dataclass
class Entry:
    key: str
    value: str


class EntryEditor:
    def __init__(
        self,
        stdscr: Any,
        entry: Entry,
        on_save: Callable[[str], bool],
        validator: Optional[Callable[[str], Optional[str]]] = None,
        type_label: Optional[str] = None,
        subkeys: Optional[List[str]] = None,
    ) -> None:
        self.stdscr = stdscr
        self.entry = entry
        self.on_save = on_save
        self.validator = validator
        self.type_label = type_label or "unknown"
        self.subkeys = subkeys or []
        self.original_value = entry.value
        self._buffer = entry.value
        self._cursor = len(self._buffer)
        self._scroll = 0

    def edit(self) -> None:
        # Optional textpad-based editor: enabled when running under a real
        # curses screen and OF_TUI_USE_TEXTBOX=1 is set in the environment.
        use_textbox = (
            os.environ.get("OF_TUI_USE_TEXTBOX") == "1"
            and hasattr(self.stdscr, "derwin")
        )
        if use_textbox:
            self._edit_with_textbox()
            return

        while True:
            self._draw_layout()
            key = self.stdscr.getch()

            # Ctrl+C or 'b' cancels editing.
            if key in (3, ord("b")):
                return

            if key == curses.KEY_RESIZE:
                # Layout will be redrawn automatically on next loop.
                continue

            # 'h' triggers foamHelp prompt for the current context.
            if key == ord("h"):
                self._foam_help()
                continue

            # Enter saves current buffer.
            if key in (curses.KEY_ENTER, 10, 13):
                new_value = self._buffer
                # If user did not change anything, just leave without
                # re-validating or writing.
                if new_value == self.original_value:
                    return

                error = self.validator(new_value) if self.validator else None
                if error:
                    if not self._confirm_dangerous(new_value, error):
                        continue

                if self.on_save(new_value):
                    self.entry.value = new_value
                    self.original_value = new_value
                    self._show_message("Saved successfully. Press any key to continue.")
                    return

                self._show_message("Failed to save value. Press any key to retry.")
                continue

            # Backspace handling.
            if key in (curses.KEY_BACKSPACE, 127, 8):
                if self._cursor > 0 and self._buffer:
                    self._buffer = self._buffer[: self._cursor - 1] + self._buffer[self._cursor :]
                    self._cursor -= 1
                continue

            # Move cursor left/right with arrow keys.
            if key == curses.KEY_LEFT:
                if self._cursor > 0:
                    self._cursor -= 1
                continue
            if key == curses.KEY_RIGHT:
                if self._cursor < len(self._buffer):
                    self._cursor += 1
                continue

            # Basic printable characters.
            if 32 <= key <= 126:
                ch = chr(key)
                self._buffer = (
                    self._buffer[: self._cursor] + ch + self._buffer[self._cursor :]
                )
                self._cursor += 1
                continue

    def _edit_with_textbox(self) -> None:
        """
        Single-line editor based on curses.textpad.Textbox.

        This is an optional path used when OF_TUI_USE_TEXTBOX=1 and a
        real curses screen is available. Validation and confirmation
        are kept identical to the manual editor path.
        """
        self.stdscr.clear()
        height, width = self.stdscr.getmaxyx()
        split_col = max(20, width // 2)

        # Left pane: old entry preview (mirrors _draw_layout).
        left_width = split_col - 1
        header = "=== Config Editor ==="
        try:
            self.stdscr.addstr(0, 0, header[: max(1, left_width)])
            self.stdscr.addstr(2, 0, f"Key: {self.entry.key}"[: max(1, left_width)])
            self.stdscr.addstr(3, 0, "Old entry:"[: max(1, left_width)])
            row = 4
            for line in self.original_value.splitlines() or [self.original_value]:
                if row >= height:
                    break
                self.stdscr.addstr(row, 0, line[: max(1, left_width)])
                row += 1
        except curses.error:
            pass

        # Right pane header.
        right_width = width - split_col - 1
        try:
            self.stdscr.addstr(
                0,
                split_col,
                "New entry (empty to clear):"[: max(1, right_width)],
            )
            self.stdscr.addstr(
                1,
                split_col,
                f"Type: {self.type_label}"[: max(1, right_width)],
            )
        except curses.error:
            pass

        # Input line using Textbox.
        try:
            prompt = "> "
            self.stdscr.addstr(3, split_col, prompt[: max(1, right_width)])
            input_width = max(1, right_width - len(prompt))
            win = self.stdscr.derwin(1, input_width, 3, split_col + len(prompt))
        except curses.error:
            # Fallback to manual editor if window creation fails.
            self.edit()
            return

        # Pre-fill with current buffer.
        win.erase()
        win.addstr(0, 0, self._buffer[: input_width])

        tb = textpad.Textbox(win, insert_mode=True)
        curses.curs_set(1)
        try:
            text = tb.edit()
        finally:
            try:
                curses.curs_set(0)
            except curses.error:
                pass

        new_value = text.rstrip("\n")
        # If unchanged, exit without validation or write.
        if new_value == self.original_value:
            return

        error = self.validator(new_value) if self.validator else None
        if error:
            if not self._confirm_dangerous(new_value, error):
                return

        if self.on_save(new_value):
            self.entry.value = new_value
            self.original_value = new_value
            self._show_message("Saved successfully. Press any key to continue.")
        else:
            self._show_message("Failed to save value. Press any key to retry.")

    def _foam_help(self) -> None:
        """
        Run foamHelp with user-provided arguments while editing an entry.

        This is intended for looking up documentation on utilities,
        boundary conditions, etc., without leaving the editor.
        """
        curses.echo()
        self.stdscr.clear()
        self.stdscr.addstr("foamHelp args (e.g. -field U): ")
        self.stdscr.refresh()
        arg_line = self.stdscr.getstr().decode().strip()
        curses.noecho()

        if not arg_line:
            return

        parts = arg_line.split()
        try:
            result = subprocess.run(
                ["foamHelp", *parts],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            self._show_message(f"Failed to run foamHelp: {exc}")
            return

        output = result.stdout or result.stderr or "(no output)"
        viewer = Viewer(self.stdscr, output)
        viewer.display()

    def _draw_layout(self) -> None:
        self.stdscr.clear()
        height, width = self.stdscr.getmaxyx()
        split_col = max(20, width // 2)

        # Left pane: old entry preview.
        left_width = split_col - 1
        header = "=== Config Editor ==="
        try:
            self.stdscr.addstr(0, 0, header[: max(1, left_width)])
            self.stdscr.addstr(2, 0, f"Key: {self.entry.key}"[: max(1, left_width)])
            self.stdscr.addstr(3, 0, "Old entry:"[: max(1, left_width)])
            row = 4
            for line in self.original_value.splitlines() or [self.original_value]:
                if row >= height:
                    break
                self.stdscr.addstr(row, 0, line[: max(1, left_width)])
                row += 1
        except curses.error:
            pass

        # Right pane: new entry input and metadata.
        right_width = width - split_col - 1
        try:
            self.stdscr.addstr(
                0,
                split_col,
                "New entry (empty to clear):"[: max(1, right_width)],
            )
            self.stdscr.addstr(
                1,
                split_col,
                f"Type: {self.type_label}"[: max(1, right_width)],
            )

            # Clamp cursor within current buffer.
            if self._cursor < 0:
                self._cursor = 0
            if self._cursor > len(self._buffer):
                self._cursor = len(self._buffer)

            # Determine horizontal view window around cursor for long lines.
            view_width = max(1, right_width - 2)  # account for '> '
            if self._cursor < self._scroll:
                self._scroll = self._cursor
            elif self._cursor > self._scroll + view_width:
                self._scroll = self._cursor - view_width
            if self._scroll < 0:
                self._scroll = 0
            visible = self._buffer[self._scroll : self._scroll + view_width]

            # Visible input field with current buffer slice.
            input_label = "> " + visible
            self.stdscr.addstr(3, split_col, input_label[: max(1, right_width)])

            # Move cursor to current position within visible slice.
            cursor_col = min(
                split_col + 2 + (self._cursor - self._scroll),  # 2 chars for the "> "
                split_col + max(1, right_width) - 1,
            )
            self.stdscr.move(3, cursor_col)
        except curses.error:
            pass

        # Sub-keys (if any) as context below type.
        row = 5
        if self.subkeys and row < height:
            try:
                self.stdscr.addstr(
                    row,
                    split_col,
                    "Sub-keys:"[: max(1, right_width)],
                )
            except curses.error:
                pass
            row += 1
            for sub in self.subkeys:
                if row >= height:
                    break
                try:
                    self.stdscr.addstr(
                        row,
                        split_col,
                        f"- {sub}"[: max(1, right_width)],
                    )
                except curses.error:
                    break
                row += 1

        self.stdscr.refresh()

    def _show_message(self, message: str) -> None:
        self.stdscr.clear()
        self.stdscr.addstr(message + "\n")
        self.stdscr.refresh()
        self.stdscr.getch()

    def _confirm_dangerous(self, value: str, error: str) -> bool:
        """
        Ask the user whether to continue with a value that failed validation.

        Returns True if the user chooses to continue anyway.
        """
        self.stdscr.clear()
        self.stdscr.addstr("Value seems wrong:\n")
        self.stdscr.addstr(f"  {error}\n\n")
        self.stdscr.addstr(f"Proposed value:\n  {value}\n\n")
        self.stdscr.addstr("Continue anyway? (y/N): ")
        self.stdscr.refresh()

        ch = self.stdscr.getch()
        return ch in (ord("y"), ord("Y"))


class Viewer:
    def __init__(self, stdscr: Any, content: str) -> None:
        self.stdscr = stdscr
        self.content = content

    def display(self) -> None:
        lines = self.content.splitlines()
        start_line = 0
        search_term: Optional[str] = None

        while True:
            self.stdscr.erase()
            height, width = self.stdscr.getmaxyx()
            header = "Press 'q' to exit, '?' for help."
            try:
                self.stdscr.addstr(header[: max(1, width - 1)] + "\n\n")
            except curses.error:
                pass
            end_line = start_line + height - 3

            for line in lines[start_line:end_line]:
                text = line[: max(1, width - 1)]
                try:
                    self.stdscr.addstr(text + "\n")
                except curses.error:
                    break

            self.stdscr.refresh()
            key = self.stdscr.getch()

            if key == ord("?"):
                self._show_help()
                continue

            if key == curses.KEY_RESIZE:
                # Recompute layout on next iteration.
                continue

            if key_in(key, get_config().keys.get("search", [])):
                # Simple search prompt.
                curses.echo()
                self.stdscr.clear()
                self.stdscr.addstr("Search: ")
                self.stdscr.refresh()
                query = self.stdscr.getstr().decode()
                curses.noecho()
                if query:
                    search_term = query
                    # Find next occurrence after current window.
                    start_index = end_line
                    found = None
                    for i in range(start_index, len(lines)):
                        if search_term in lines[i]:
                            found = i
                            break
                    if found is not None:
                        start_line = found
                    else:
                        # Wrap to start.
                        for i in range(0, len(lines)):
                            if search_term in lines[i]:
                                start_line = i
                                break
                continue

            if key_in(key, get_config().keys.get("back", [])):
                return
            if key_in(key, get_config().keys.get("top", [])):
                start_line = 0
            if key_in(key, get_config().keys.get("bottom", [])):
                start_line = max(0, len(lines) - (height - 3))
            if key in (curses.KEY_DOWN,) or key_in(key, get_config().keys.get("down", [])):
                if end_line < len(lines):
                    start_line += 1
            if key in (curses.KEY_UP,) or key_in(key, get_config().keys.get("up", [])):
                if start_line > 0:
                    start_line -= 1

    def _show_help(self) -> None:
        self.stdscr.clear()
        self.stdscr.addstr("Viewer help\n\n")
        self.stdscr.addstr("  j / k or arrows : scroll\n")
        self.stdscr.addstr("  g / G           : top / bottom\n")
        self.stdscr.addstr("  q               : exit viewer\n")
        self.stdscr.addstr("  /               : search within file\n")
        self.stdscr.addstr("  ?               : show this help\n\n")
        self.stdscr.addstr("Press any key to return.\n")
        self.stdscr.refresh()
        self.stdscr.getch()

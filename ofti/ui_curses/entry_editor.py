from __future__ import annotations

import curses
import os
from collections.abc import Callable
from contextlib import suppress
from curses import textpad
from typing import Any

from ofti.core.entries import Entry
from ofti.foam.config import get_config, key_in
from ofti.foam.exceptions import QuitAppError
from ofti.foam.subprocess_utils import resolve_executable, run_trusted
from ofti.ui_curses.viewer import Viewer


class EntryEditor:
    def __init__(
        self,
        stdscr: Any,
        entry: Entry,
        on_save: Callable[[str], bool],
        validator: Callable[[str], str | None] | None = None,
        type_label: str | None = None,
        subkeys: list[str] | None = None,
        case_label: str | None = None,
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
        self.case_label = case_label

    def edit(self) -> None:  # noqa: C901, PLR0912
        use_textbox = (
            os.environ.get("OFTI_USE_TEXTBOX") == "1"
            and hasattr(self.stdscr, "derwin")
        )
        if use_textbox:
            self._edit_with_textbox()
            return

        while True:
            self._draw_layout()
            key = self.stdscr.getch()

            if key_in(key, get_config().keys.get("quit", [])):
                raise QuitAppError()

            if key in (3, 27):
                return

            if key == curses.KEY_RESIZE:
                continue

            if key == ord("K"):
                self._foam_help()
                continue

            if key in (curses.KEY_ENTER, 10, 13):
                new_value = self._buffer
                if new_value == self.original_value:
                    return

                if get_config().validate_on_save:
                    error = self.validator(new_value) if self.validator else None
                    if error and not self._confirm_dangerous(new_value, error):
                        continue

                if self.on_save(new_value):
                    self.entry.value = new_value
                    self.original_value = new_value
                    self._show_message("Saved successfully. Press any key to continue.")
                    return

                self._show_message("Failed to save value. Press any key to retry.")
                continue

            if key in (curses.KEY_BACKSPACE, 127, 8):
                if self._cursor > 0 and self._buffer:
                    self._buffer = self._buffer[: self._cursor - 1] + self._buffer[self._cursor :]
                    self._cursor -= 1
                continue

            if key == curses.KEY_LEFT:
                if self._cursor > 0:
                    self._cursor -= 1
                continue
            if key == curses.KEY_RIGHT:
                if self._cursor < len(self._buffer):
                    self._cursor += 1
                continue

            if 32 <= key <= 126:
                ch = chr(key)
                self._buffer = (
                    self._buffer[: self._cursor] + ch + self._buffer[self._cursor :]
                )
                self._cursor += 1
                continue

    def _edit_with_textbox(self) -> None:
        self.stdscr.clear()
        height, width = self.stdscr.getmaxyx()
        split_col = max(20, width // 2)

        left_width = split_col - 1
        header = _entry_editor_header(self.case_label)
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

        try:
            prompt = "> "
            self.stdscr.addstr(3, split_col, prompt[: max(1, right_width)])
            input_width = max(1, right_width - len(prompt))
            win = self.stdscr.derwin(1, input_width, 3, split_col + len(prompt))
        except curses.error:
            self.edit()
            return

        win.erase()
        win.addstr(0, 0, self._buffer[: input_width])

        tb = textpad.Textbox(win, insert_mode=True)
        curses.curs_set(1)
        try:
            text = tb.edit()
        finally:
            with suppress(curses.error):
                curses.curs_set(0)

        new_value = text.rstrip("\n")
        if new_value == self.original_value:
            return

        if get_config().validate_on_save:
            error = self.validator(new_value) if self.validator else None
            if error and not self._confirm_dangerous(new_value, error):
                return

        if self.on_save(new_value):
            self.entry.value = new_value
            self.original_value = new_value
            self._show_message("Saved successfully. Press any key to continue.")
            return

        self._show_message("Failed to save value. Press any key to retry.")

    def _draw_layout(self) -> None:
        self.stdscr.clear()
        height, width = self.stdscr.getmaxyx()
        split_col = max(20, width // 2)

        left_width = split_col - 1
        header = _entry_editor_header(self.case_label)
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
            self.stdscr.addstr(
                2,
                split_col,
                "Keys: Enter=save  Esc/Ctrl+C=back"[: max(1, right_width)],
            )

            self._cursor = max(self._cursor, 0)
            self._cursor = min(self._cursor, len(self._buffer))

            view_width = max(1, right_width - 2)
            if self._cursor < self._scroll:
                self._scroll = self._cursor
            elif self._cursor > self._scroll + view_width:
                self._scroll = self._cursor - view_width
            self._scroll = max(self._scroll, 0)
            visible = self._buffer[self._scroll : self._scroll + view_width]

            input_label = "> " + visible
            self.stdscr.addstr(3, split_col, input_label[: max(1, right_width)])

            cursor_col = min(
                split_col + 2 + (self._cursor - self._scroll),
                split_col + max(1, right_width) - 1,
            )
            self.stdscr.move(3, cursor_col)
        except curses.error:
            pass

    def _show_message(self, message: str) -> None:
        self.stdscr.clear()
        self.stdscr.addstr(message + "\n")
        self.stdscr.addstr("Press any key to continue.\n")
        self.stdscr.refresh()
        key = self.stdscr.getch()
        if key_in(key, get_config().keys.get("quit", [])):
            raise QuitAppError()

    def _foam_help(self) -> None:
        keyword = self.entry.key
        parts = keyword.split(".")
        if parts and parts[0]:
            try:
                resolved = resolve_executable("foamHelp")
                result = run_trusted(
                    [resolved, *parts],
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

    def _confirm_dangerous(self, value: str, error: str) -> bool:
        self.stdscr.clear()
        self.stdscr.addstr("Value seems wrong:\n")
        self.stdscr.addstr(f"  {error}\n\n")
        self.stdscr.addstr(f"Proposed value:\n  {value}\n\n")
        self.stdscr.addstr("Continue anyway? (y/N): ")
        self.stdscr.refresh()

        ch = self.stdscr.getch()
        return ch in (ord("y"), ord("Y"))

    def _check_value(self) -> None:
        if self.validator is None:
            self._show_message("No validator available for this entry.")
            return
        error = self.validator(self._buffer)
        if error:
            self._show_message(f"Check failed: {error}")
        else:
            self._show_message("Check OK.")


def _entry_editor_header(case_label: str | None) -> str:
    if case_label:
        return f"=== OFTI ({case_label}) ==="
    return "=== OFTI ==="

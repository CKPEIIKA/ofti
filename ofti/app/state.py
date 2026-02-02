from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ofti.foam.openfoam import FileCheckResult
from ofti.foam.tasks import TaskRegistry
from ofti.ui_curses.layout import next_spinner


class Screen(Enum):
    MAIN_MENU = "main_menu"
    EDITOR = "editor"
    ENTRY_BROWSER = "entry_browser"
    CHECK = "check"
    TOOLS = "tools"
    DIAGNOSTICS = "diagnostics"
    SEARCH = "search"
    VIEWER = "viewer"
    NO_FOAM_FILE = "no_foam_file"


@dataclass
class AppState:
    no_foam: bool = False
    no_foam_reason: str | None = None
    current_screen: Screen = Screen.MAIN_MENU
    last_action: str | None = None
    last_section: str | None = None
    last_file: str | None = None
    menu_selection: dict[str, int] = field(default_factory=dict)
    check_lock: threading.Lock = field(default_factory=threading.Lock)
    check_in_progress: bool = False
    check_total: int = 0
    check_done: int = 0
    check_current: Path | None = None
    check_results: dict[Path, FileCheckResult] | None = None
    check_thread: threading.Thread | None = None
    tasks: TaskRegistry = field(default_factory=TaskRegistry)
    case_meta: dict[str, str] | None = None
    case_meta_at: float | None = None
    case_metadata_path: Path | None = None
    case_metadata: dict[str, str] | None = None

    def transition(self, screen: Screen, action: str | None = None) -> None:
        self.current_screen = screen
        if action is not None:
            self.last_action = action

    def check_status_line(self) -> str:
        with self.check_lock:
            if self.check_in_progress:
                current = f" {self.check_current.name}" if self.check_current else ""
                return f"{next_spinner()} check: {self.check_done}/{self.check_total}{current}"
        return ""

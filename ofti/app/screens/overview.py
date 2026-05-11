from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.app.overview import overview_text
from ofti.ui_curses.viewer import Viewer


def overview_screen(stdscr: Any, case_path: Path) -> None:
    Viewer(stdscr, overview_text(case_path)).display()

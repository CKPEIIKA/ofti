from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ofti.app.state import AppState, Screen

ScreenHandler = Callable[[Any, Any, AppState], Screen | None]


@dataclass
class ScreenRouter:
    handlers: dict[Screen, ScreenHandler]

    def dispatch(
        self,
        screen: Screen | None,
        stdscr: Any,
        case_path: Any,
        state: AppState,
    ) -> Screen | None:
        if screen is None:
            return None
        handler = self.handlers.get(screen)
        if handler is None:
            return Screen.MAIN_MENU
        return handler(stdscr, case_path, state)

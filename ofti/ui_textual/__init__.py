"""Optional Textual-based mission control deck.

This package is a thin UI adapter over the shared deck model in
``ofti.ui.deck``. It only works when the optional ``tui`` extra is
installed; everything else in OFTI must keep working without it.
"""

from __future__ import annotations

import importlib.util

TUI_EXTRA_HINT = "Mission control deck needs the optional extra: pip install 'ofti[tui]'"


def textual_available() -> bool:
    return importlib.util.find_spec("textual") is not None

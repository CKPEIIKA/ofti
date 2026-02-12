from __future__ import annotations

import itertools

_SPINNER = itertools.cycle("|/-\\")


def next_spinner() -> str:
    return next(_SPINNER)

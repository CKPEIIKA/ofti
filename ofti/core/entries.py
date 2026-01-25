from __future__ import annotations

from dataclasses import dataclass


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

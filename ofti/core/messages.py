from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Message:
    level: str
    text: str


def info(text: str) -> Message:
    return Message(level="info", text=text)


def warn(text: str) -> Message:
    return Message(level="warn", text=text)


def error(text: str) -> Message:
    return Message(level="error", text=text)

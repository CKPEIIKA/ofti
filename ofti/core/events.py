from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Event:
    name: str
    payload: dict[str, str] | None = None


def navigate(target: str) -> Event:
    return Event(name="navigate", payload={"target": target})


def notify(message: str) -> Event:
    return Event(name="notify", payload={"message": message})

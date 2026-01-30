import curses
from pathlib import Path
from unittest import mock

from ofti.tools import PIPELINE_HEADER, dictionary_compare_screen, pipeline_runner_screen


class FakeScreen:
    def __init__(self, keys=None, inputs=None) -> None:
        self._keys = list(keys or [])
        self._inputs = [s.encode() for s in (inputs or [])]

    def clear(self) -> None:
        pass

    def erase(self) -> None:
        pass

    def getmaxyx(self):
        return (24, 80)

    def getyx(self):
        return (0, 0)

    def addstr(self, *args, **kwargs) -> None:
        pass

    def attron(self, *args, **kwargs) -> None:
        pass

    def attroff(self, *args, **kwargs) -> None:
        pass

    def refresh(self) -> None:
        pass

    def move(self, *_args, **_kwargs) -> None:
        pass

    def clrtoeol(self) -> None:
        pass

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("h")

    def getstr(self):
        if self._inputs:
            return self._inputs.pop(0)
        return b""


def test_pipeline_runner_screen_runs_commands(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    pipeline = case_dir / "Allrun"
    pipeline.write_text("\n".join(["#!/bin/bash", PIPELINE_HEADER, "echo hello"]))

    screen = FakeScreen(keys=[ord("h")])
    completed = mock.Mock(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr("ofti.tools.pipeline.run_trusted", lambda *_args, **_kwargs: completed)
    pipeline_runner_screen(screen, case_dir)


def test_dictionary_compare_screen(monkeypatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "caseA"
    other = tmp_path / "caseB"
    case_dir.mkdir()
    other.mkdir()

    screen = FakeScreen(keys=[ord("h")], inputs=[str(other)])
    monkeypatch.setattr(curses, "echo", lambda *_: None)
    monkeypatch.setattr(curses, "noecho", lambda *_: None)
    monkeypatch.setattr("ofti.tools.compare_case_dicts", lambda *_: [])

    dictionary_compare_screen(screen, case_dir)

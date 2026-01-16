"""Coverage for tool cleaning fallbacks and dict prompts."""

from __future__ import annotations

from pathlib import Path

import of_tui.tools as tools
import of_tui.config as config


class FakeScreen:
    def __init__(self, keys=None) -> None:
        self._keys = list(keys or [])
        self.lines: list[str] = []
        self.height = 24
        self.width = 80

    def clear(self) -> None:
        self.lines.clear()

    def addstr(self, *args) -> None:
        self.lines.append(str(args[-1]))

    def refresh(self) -> None:
        pass

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("q")

    def getmaxyx(self):
        return (self.height, self.width)


def _reset_config() -> None:
    config._CONFIG = None


def test_remove_all_logs_fallback(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "log.a").write_text("a")
    (case_dir / "log.b").write_text("b")

    monkeypatch.delenv("WM_PROJECT_DIR", raising=False)
    monkeypatch.setenv("OF_TUI_USE_CLEANFUNCTIONS", "0")
    _reset_config()

    screen = FakeScreen()
    tools.remove_all_logs(screen, case_dir)

    assert not list(case_dir.glob("log.*"))


def test_clean_time_directories_fallback(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "0").mkdir()
    (case_dir / "1.5").mkdir()
    (case_dir / "ignore").mkdir()
    (case_dir / "1.5" / "data.txt").write_text("x")

    monkeypatch.delenv("WM_PROJECT_DIR", raising=False)
    monkeypatch.setenv("OF_TUI_USE_CLEANFUNCTIONS", "0")
    _reset_config()

    screen = FakeScreen()
    tools.clean_time_directories(screen, case_dir)

    assert not (case_dir / "0").exists()
    assert not (case_dir / "1.5").exists()
    assert (case_dir / "ignore").exists()


def test_run_current_solver_fallback(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;\n")
    screen = FakeScreen()

    called = []

    def fake_run_simple(_stdscr, _case, name, cmd):
        called.append((name, cmd))

    monkeypatch.setattr(tools, "_run_simple_tool", fake_run_simple)
    monkeypatch.delenv("WM_PROJECT_DIR", raising=False)
    monkeypatch.setenv("OF_TUI_USE_RUNFUNCTIONS", "0")
    _reset_config()
    monkeypatch.setattr(tools, "read_entry", lambda *_args, **_kwargs: "simpleFoam;")

    tools.run_current_solver(screen, case_dir)

    assert called and called[0][0] == "simpleFoam"


def test_ensure_tool_dict_decline(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    screen = FakeScreen(keys=[ord("n")])
    target = case_dir / "system" / "postProcessDict"

    ok = tools._ensure_tool_dict(
        screen,
        case_dir,
        "postProcess",
        target,
        ["postProcess", "-list"],
    )

    assert ok is False
    assert not target.exists()

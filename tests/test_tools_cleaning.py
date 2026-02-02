"""Coverage for tool cleaning fallbacks and dict prompts."""

from __future__ import annotations

from pathlib import Path

from ofti.foam import config
from ofti.tools.cleaning_ops import clean_time_directories, remove_all_logs


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
        return ord("h")

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
    monkeypatch.setenv("OFTI_USE_CLEANFUNCTIONS", "0")
    _reset_config()

    screen = FakeScreen()
    remove_all_logs(screen, case_dir)

    assert not list(case_dir.glob("log.*"))


def test_clean_time_directories_fallback(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "0").mkdir()
    (case_dir / "1.5").mkdir()
    (case_dir / "ignore").mkdir()
    (case_dir / "1.5" / "data.txt").write_text("x")

    monkeypatch.delenv("WM_PROJECT_DIR", raising=False)
    monkeypatch.setenv("OFTI_USE_CLEANFUNCTIONS", "0")
    _reset_config()

    screen = FakeScreen()
    clean_time_directories(screen, case_dir)

    assert (case_dir / "0").exists()
    assert not (case_dir / "1.5").exists()
    assert (case_dir / "ignore").exists()


def test_run_current_solver_fallback(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;\n")
    zero_dir = case_dir / "0"
    zero_dir.mkdir()
    (zero_dir / "U").write_text("internalField uniform (0 0 0);\n")
    (zero_dir / "p").write_text("internalField uniform 0;\n")
    screen = FakeScreen()

    called = []

    def fake_run_simple(_stdscr, _case, name, cmd, **_kwargs):
        called.append((name, cmd))

    monkeypatch.setattr("ofti.tools.solver._run_simple_tool", fake_run_simple)
    monkeypatch.delenv("WM_PROJECT_DIR", raising=False)
    monkeypatch.setenv("OFTI_USE_RUNFUNCTIONS", "0")
    _reset_config()
    monkeypatch.setattr("ofti.core.solver_checks.read_entry", lambda *_args, **_kwargs: "simpleFoam;")

    from ofti.tools.solver import run_current_solver

    run_current_solver(screen, case_dir)

    assert called and called[0][0] == "simpleFoam"


def test_ensure_tool_dict_decline(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    screen = FakeScreen(keys=[ord("n")])
    target = case_dir / "system" / "postProcessDict"

    from ofti.ui_curses.tool_dicts_ui import _ensure_tool_dict

    ok = _ensure_tool_dict(
        screen,
        case_dir,
        "postProcess",
        target,
        ["postProcess", "-list"],
    )

    assert ok is False
    assert not target.exists()

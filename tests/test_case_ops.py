from __future__ import annotations

from pathlib import Path

from ofti.tools import case_ops


class DummyViewer:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def display(self) -> None:
        pass


class FakeScreen:
    def clear(self) -> None:
        pass

    def addstr(self, *_args, **_kwargs) -> None:
        pass

    def refresh(self) -> None:
        pass


def test_clone_case_creates_destination(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "system").mkdir()
    (case_dir / "system" / "controlDict").write_text("application simpleFoam;\n")
    (case_dir / "log.simpleFoam").write_text("log")
    (case_dir / "0").mkdir()
    (case_dir / "0" / "U").write_text("internalField uniform (0 0 0);\n")

    monkeypatch.setattr(case_ops, "Viewer", DummyViewer)
    screen = FakeScreen()

    case_ops.clone_case(screen, case_dir, name="case_copy")

    dest = case_dir.parent / "case_copy"
    assert dest.is_dir()


def test_open_paraview_screen_reports_missing_binary(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    messages: list[str] = []

    def capture_message(_screen, message: str) -> None:
        messages.append(message)

    monkeypatch.setattr(case_ops, "_show_message", capture_message)
    monkeypatch.setattr(case_ops.shutil, "which", lambda _cmd: None)

    screen = FakeScreen()
    case_ops.open_paraview_screen(screen, case_dir)

    assert any("paraview not found" in msg for msg in messages)

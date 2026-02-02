from __future__ import annotations

from pathlib import Path

from ofti.app.clean_menu import clean_all


class FakeScreen:
    def clear(self) -> None:
        pass

    def addstr(self, *_args, **_kwargs) -> None:
        pass

    def refresh(self) -> None:
        pass


def test_clean_all_removes_processor_dirs(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    proc = case_dir / "processor0"
    proc.mkdir()
    (proc / "dummy").write_text("x")

    monkeypatch.setattr("ofti.app.clean_menu.remove_all_logs", lambda *_a, **_k: None)
    monkeypatch.setattr("ofti.app.clean_menu.clean_time_directories", lambda *_a, **_k: None)
    monkeypatch.setattr("ofti.app.clean_menu.reconstruct_latest_once", lambda *_: (True, ""))
    monkeypatch.setattr("ofti.app.clean_menu.status_message", lambda *_: None)
    monkeypatch.setattr("ofti.app.clean_menu._show_message", lambda *_: None)

    clean_all(FakeScreen(), case_dir)

    assert not proc.exists()

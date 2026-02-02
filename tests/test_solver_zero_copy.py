from __future__ import annotations

from pathlib import Path

from ofti.tools.solver import _ensure_zero_dir


class FakeScreen:
    def __init__(self, keys=None) -> None:
        self._keys = list(keys or [])

    def clear(self) -> None:
        pass

    def addstr(self, *_args, **_kwargs) -> None:
        pass

    def refresh(self) -> None:
        pass

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("n")


def test_ensure_zero_dir_copies_from_orig(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    zero_orig = case_dir / "0.orig"
    zero_orig.mkdir()
    (zero_orig / "U").write_text("internalField uniform (0 0 0);\n")

    screen = FakeScreen(keys=[ord("y")])
    assert _ensure_zero_dir(screen, case_dir)
    assert (case_dir / "0").is_dir()

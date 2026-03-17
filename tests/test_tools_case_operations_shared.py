from __future__ import annotations

from pathlib import Path

from ofti.tools import menus


def test_case_operations_screen_uses_shared_case_tools(
    monkeypatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    calls: list[str] = []

    choices = iter([0, 1, 2, 3, 4])
    monkeypatch.setattr(menus, "_case_operations_menu", lambda *_a, **_k: next(choices))
    monkeypatch.setattr(
        menus.shared_case_tools,
        "show_preflight_screen",
        lambda *_a, **_k: calls.append("preflight"),
    )
    monkeypatch.setattr(
        menus.case_doctor,
        "case_doctor_screen",
        lambda *_a, **_k: calls.append("doctor"),
    )
    monkeypatch.setattr(
        menus.shared_case_tools,
        "show_case_status_screen",
        lambda *_a, **_k: calls.append("status"),
    )
    monkeypatch.setattr(
        menus.shared_case_tools,
        "compare_dictionaries_screen",
        lambda *_a, **_k: calls.append("compare"),
    )

    menus.case_operations_screen(object(), case)

    assert calls == ["preflight", "doctor", "status", "compare"]

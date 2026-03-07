from __future__ import annotations

import types
from pathlib import Path

import pytest

from ofti.tools import run
from tests.testscreen import TestScreen as _Screen


def _capture_viewer(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    shown: list[str] = []

    class _Viewer:
        def __init__(self, _screen: object, text: str) -> None:
            shown.append(text)

        def display(self) -> None:
            return None

    monkeypatch.setattr(run, "Viewer", _Viewer)
    return shown


def test_run_checkmesh_and_blockmesh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen()
    seen: list[tuple[str, object]] = []

    monkeypatch.setattr(run, "run_tool_command_capture", lambda *_a, **_k: None)
    monkeypatch.setattr(run, "_show_checkmesh_summary", lambda *_a, **_k: seen.append(("summary", None)))
    run.run_checkmesh(screen, case)
    assert seen == []

    monkeypatch.setattr(
        run,
        "run_tool_command_capture",
        lambda *_a, **_k: types.SimpleNamespace(stdout="ok", stderr="warn"),
    )
    run.run_checkmesh(screen, case)
    assert seen == [("summary", None)]

    commands: list[list[str]] = []
    monkeypatch.setattr(run, "run_tool_command", lambda *_a, **_k: commands.append(list(_a[3])))
    run.run_blockmesh(screen, case)
    assert commands == [["blockMesh"]]


def test_run_decomposepar_create_and_execute(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen(keys=[ord("x")])
    messages: list[str] = []
    monkeypatch.setattr(run, "_show_message", lambda _s, text: messages.append(text))

    created: list[bool] = []
    monkeypatch.setattr(run, "write_example_template", lambda *_a, **_k: created.append(True) or True)
    run.run_decomposepar(screen, case)
    assert created == []

    screen_yes = _Screen(keys=[ord("c")])
    run.run_decomposepar(screen_yes, case)
    assert messages[-1] == "Created decomposeParDict from examples."

    monkeypatch.setattr(run, "write_example_template", lambda *_a, **_k: False)
    run.run_decomposepar(_Screen(keys=[ord("c")]), case)
    assert messages[-1] == "No example template found for decomposeParDict."

    (case / "system").mkdir(exist_ok=True)
    (case / "system" / "decomposeParDict").write_text("numberOfSubdomains 2;\n")
    calls: list[list[str]] = []
    monkeypatch.setattr(run, "run_tool_command", lambda *_a, **_k: calls.append(list(_a[3])))
    run.run_decomposepar(_Screen(), case)
    assert calls[-1] == ["decomposePar"]


def test_show_checkmesh_summary_and_parallel_report(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    shown = _capture_viewer(monkeypatch)
    monkeypatch.setattr(run, "format_checkmesh_summary", lambda _text: "summary")
    monkeypatch.setattr(run, "format_log_blob", lambda out, err: f"{out}|{err}")

    run._show_checkmesh_summary(_Screen(keys=[ord("h")]), "out", "err")
    assert shown == []

    run._show_checkmesh_summary(_Screen(keys=[ord("r")]), "out", "err")
    assert "checkMesh raw output" in shown[-1]
    assert "out|err" in shown[-1]

    status, lines = run._parallel_consistency_report(case)
    assert status == "missing"
    assert "system/decomposeParDict not found." in lines[-1]

    (case / "system").mkdir()
    decompose = case / "system" / "decomposeParDict"
    decompose.write_text("numberOfSubdomains bad;\n")
    monkeypatch.setattr(run, "read_number_of_subdomains", lambda _path: None)
    status, lines = run._parallel_consistency_report(case)
    assert status == "warn"
    assert "invalid" in lines[0]

    monkeypatch.setattr(run, "read_number_of_subdomains", lambda _path: 2)
    (case / "processor0").mkdir()
    status, _ = run._parallel_consistency_report(case)
    assert status == "mismatch"
    (case / "processor1").mkdir()
    status, _ = run._parallel_consistency_report(case)
    assert status == "ok"

    run.parallel_consistency_screen(_Screen(), case)
    assert "OK: counts match." in shown[-1]


def test_decomposed_processors_sorted(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    (case / "processor10").mkdir()
    (case / "processor2").mkdir()
    (case / "notes").mkdir()
    names = [path.name for path in run._decomposed_processors(case)]
    assert names == ["processor10", "processor2"]


def test_parallel_consistency_screen_warn_and_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    shown = _capture_viewer(monkeypatch)
    monkeypatch.setattr(run, "_parallel_consistency_report", lambda _case: ("warn", ["numberOfSubdomains not set"]))
    run.parallel_consistency_screen(_Screen(), Path())
    assert "Add numberOfSubdomains to decomposeParDict." in shown[-1]

    monkeypatch.setattr(run, "_parallel_consistency_report", lambda _case: ("mismatch", ["numberOfSubdomains: 4"]))
    run.parallel_consistency_screen(_Screen(), Path())
    assert "Mismatch: re-run decomposePar or update dict." in shown[-1]

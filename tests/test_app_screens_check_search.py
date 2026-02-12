from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ofti.app.screens import check, search
from ofti.app.state import AppState
from ofti.foam.openfoam import FileCheckResult


def test_check_labels_reports_all_statuses(tmp_path: Path) -> None:
    case_path = tmp_path / "case"
    system = case_path / "system"
    system.mkdir(parents=True)
    a = system / "a"
    b = system / "b"
    c = system / "c"
    d = system / "d"
    for path in (a, b, c, d):
        path.write_text("FoamFile{version 2.0;}")

    state = AppState()
    state.check_results = {
        b: FileCheckResult(checked=True),
        c: FileCheckResult(checked=True, warnings=["warn"]),
        d: FileCheckResult(checked=True, errors=["err"]),
    }

    labels, checks = check.check_labels(case_path, [a, b, c, d], state)

    assert labels[0].endswith("Not checked")
    assert labels[1].endswith("OK")
    assert labels[2].endswith("Warn (1)")
    assert labels[3].endswith("ERROR (1)")
    assert checks[0] is None


def test_auto_fix_missing_required_entries_inserts_from_example(
    tmp_path: Path,
    monkeypatch,
) -> None:
    case_path = tmp_path / "case"
    control = case_path / "system" / "controlDict"
    control.parent.mkdir(parents=True)
    control.write_text("FoamFile{version 2.0; object controlDict;}")
    example = tmp_path / "example_controlDict"
    example.write_text("FoamFile{version 2.0; object controlDict;}")

    inserted: list[tuple[list[str], str]] = []
    messages: list[str] = []

    monkeypatch.setattr(check, "find_example_file", lambda _rel: example)
    monkeypatch.setattr(
        check,
        "read_entry",
        lambda _path, key: {"solvers.p": "PCG;", "solvers.U": "smoothSolver;"}[key],
    )
    monkeypatch.setattr(
        check,
        "apply_assignment_or_write",
        lambda _case, _file, keys, value: inserted.append((keys, value)) or True,
    )
    monkeypatch.setattr(check, "show_message", lambda _screen, msg: messages.append(msg))

    result = FileCheckResult(
        checked=True,
        errors=["solvers: missing required entries: p, U"],
    )
    check.auto_fix_missing_required_entries(
        stdscr=object(),
        file_path=control,
        rel_path=Path("system/controlDict"),
        result=result,
    )

    assert inserted == [
        (["solvers", "p"], "PCG;"),
        (["solvers", "U"], "smoothSolver;"),
    ]
    assert messages and messages[0].startswith("Inserted entries:")


def test_global_search_screen_reports_missing_fzf(monkeypatch, tmp_path: Path) -> None:
    messages: list[str] = []
    monkeypatch.setattr(search, "fzf_enabled", lambda: False)
    monkeypatch.setattr(search, "show_message", lambda _screen, msg: messages.append(msg))

    search.global_search_screen(
        stdscr=object(),
        case_path=tmp_path,
        state=AppState(),
        browser_callbacks=SimpleNamespace(),
    )

    assert messages == ["fzf not available (disabled or missing)."]


def test_global_search_screen_reports_parse_failures(monkeypatch, tmp_path: Path) -> None:
    case_path = tmp_path / "case"
    file_path = case_path / "system" / "controlDict"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("FoamFile{}")
    messages: list[str] = []

    monkeypatch.setattr(search, "fzf_enabled", lambda: True)
    monkeypatch.setattr(search, "discover_case_files", lambda _case: {"system": [file_path]})
    monkeypatch.setattr(search, "status_message", lambda _screen, _msg: None)
    monkeypatch.setattr(search, "list_keywords", lambda _path: (_ for _ in ()).throw(ValueError("bad parse")))
    monkeypatch.setattr(search, "show_message", lambda _screen, msg: messages.append(msg))

    search.global_search_screen(
        stdscr=object(),
        case_path=case_path,
        state=AppState(),
        browser_callbacks=SimpleNamespace(),
    )

    assert messages
    assert "could not be parsed" in messages[0]


def test_collect_search_keys_includes_nested(monkeypatch, tmp_path: Path) -> None:
    field = tmp_path / "dict"
    field.write_text(
        "\n".join(
            [
                "transportModels",
                "{",
                "    mixingRule Wilke;",
                "    NN",
                "    {",
                "        speciesOrder ( N2 O2 NO N O );",
                "        trimNegative true;",
                "    }",
                "}",
            ],
        ),
    )

    monkeypatch.setattr(search, "list_keywords", lambda _path: ["transportModels", "application"])

    keys = search._collect_search_keys(field)
    assert "transportModels" in keys
    assert "transportModels.mixingRule" in keys
    assert "transportModels.NN.speciesOrder" in keys


def test_global_search_reuses_session_cache(monkeypatch, tmp_path: Path) -> None:
    case_path = tmp_path / "case"
    file_path = case_path / "system" / "controlDict"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("FoamFile{}")
    state = AppState()
    calls = {"count": 0}

    monkeypatch.setattr(search, "fzf_enabled", lambda: True)
    monkeypatch.setattr(search, "discover_case_files", lambda _case: {"system": [file_path]})
    monkeypatch.setattr(search, "status_message", lambda _screen, _msg: None)

    def fake_list_keywords(_path: Path) -> list[str]:
        calls["count"] += 1
        return ["application"]

    monkeypatch.setattr(search, "list_keywords", fake_list_keywords)
    monkeypatch.setattr(search, "_collect_search_keys", lambda _path: ["application"])
    monkeypatch.setattr(search, "_start_full_index_build", lambda _case, _state: None)
    monkeypatch.setattr(
        search,
        "_run_fzf_live",
        lambda *_a, **_k: SimpleNamespace(returncode=1, stdout=""),
    )
    monkeypatch.setattr(search.curses, "def_prog_mode", lambda: None)
    monkeypatch.setattr(search.curses, "endwin", lambda: None)
    monkeypatch.setattr(search.curses, "reset_prog_mode", lambda: None)

    screen = SimpleNamespace(clear=lambda: None, refresh=lambda: None)
    search.global_search_screen(
        stdscr=screen,
        case_path=case_path,
        state=state,
        browser_callbacks=SimpleNamespace(),
    )
    search.global_search_screen(
        stdscr=screen,
        case_path=case_path,
        state=state,
        browser_callbacks=SimpleNamespace(),
    )

    assert calls["count"] == 1


def test_check_syntax_screen_foreground_path(monkeypatch, tmp_path: Path) -> None:
    case_path = tmp_path / "case"
    file_path = case_path / "system" / "controlDict"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("application simpleFoam;")
    state = AppState()
    called: dict[str, bool] = {"menu": False}

    monkeypatch.setattr(
        check,
        "get_config",
        lambda: SimpleNamespace(enable_background_checks=False),
    )
    monkeypatch.setattr(check, "discover_case_files", lambda _case: {"system": [file_path]})
    monkeypatch.setattr(
        check,
        "verify_case",
        lambda _case: {file_path: FileCheckResult(checked=True)},
    )
    monkeypatch.setattr(check, "status_message", lambda _screen, _msg: None)
    monkeypatch.setattr(
        check,
        "check_syntax_menu",
        lambda *_args, **_kwargs: called.__setitem__("menu", True),
    )

    check.check_syntax_screen(
        stdscr=object(),
        case_path=case_path,
        state=state,
        command_callbacks=SimpleNamespace(),
    )

    assert called["menu"] is True
    assert state.check_done == 1
    assert state.check_results == {file_path: FileCheckResult(checked=True)}

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ofti.tools import diagnostics, postprocessing, shell_tools, time_pruner
from ofti.tools import parametric as parametric_tools
from ofti.tools import tool_dicts_foamcalc as foamcalc
from ofti.tools import tool_dicts_postprocess as postprocess


class _Screen:
    def __init__(self, keys: list[int] | None = None) -> None:
        self._keys = list(keys or [])
        self.lines: list[str] = []
        self.timeout_value = -1

    def clear(self) -> None:
        self.lines.clear()

    def addstr(self, *args: Any) -> None:
        self.lines.append(str(args[-1]))

    def getmaxyx(self) -> tuple[int, int]:
        return (24, 120)

    def getyx(self) -> tuple[int, int]:
        return (len(self.lines), 0)

    def refresh(self) -> None:
        return

    def attron(self, *_args: Any, **_kwargs: Any) -> None:
        return

    def attroff(self, *_args: Any, **_kwargs: Any) -> None:
        return

    def move(self, *_args: Any, **_kwargs: Any) -> None:
        return

    def clrtoeol(self) -> None:
        return

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("h")

    def timeout(self, value: int) -> None:
        self.timeout_value = value


class _OneChoiceMenu:
    def __init__(self, choice: int) -> None:
        self._choice = choice

    def navigate(self) -> int:
        return self._choice


def _menu_sequence(choices: list[int]):
    queue = iter(choices)
    return lambda *_a, **_k: _OneChoiceMenu(next(queue))


def test_foamcalc_common_div_and_manual_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen()
    messages: list[str] = []
    run_cmds: list[list[str]] = []

    monkeypatch.setattr(foamcalc, "_ensure_tool_dict", lambda *_a, **_k: True)
    monkeypatch.setattr(foamcalc, "latest_time", lambda _case: "1.0")
    monkeypatch.setattr(foamcalc, "build_menu", _menu_sequence([1, 2]))
    prompt_values = iter(["U", ""])
    monkeypatch.setattr(foamcalc, "prompt_line", lambda *_a, **_k: next(prompt_values))
    monkeypatch.setattr(foamcalc, "_run_simple_tool", lambda *_a, **_k: run_cmds.append(list(_a[3])))
    foamcalc.foam_calc_prompt(screen, case)
    assert run_cmds[-1] == ["foamCalc", "div", "phi", "U", "-latestTime"]

    monkeypatch.setattr(foamcalc, "build_menu", _menu_sequence([2, 3]))
    monkeypatch.setattr(foamcalc, "prompt_args_line", lambda *_a, **_k: [])
    monkeypatch.setattr(foamcalc, "_show_message", lambda *_a, **_k: messages.append(_a[1]))
    foamcalc.foam_calc_prompt(screen, case)
    assert "No arguments provided" in messages[-1]


def test_foamcalc_returns_when_dict_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = tmp_path / "case"
    case.mkdir()
    monkeypatch.setattr(foamcalc, "_ensure_tool_dict", lambda *_a, **_k: False)
    called: list[str] = []
    monkeypatch.setattr(foamcalc, "_run_simple_tool", lambda *_a, **_k: called.append("run"))
    foamcalc.foam_calc_prompt(_Screen(), case)
    assert called == []


def test_postprocess_function_selection_and_missing_funcs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    screen = _Screen()
    run_cmds: list[list[str]] = []
    messages: list[str] = []

    monkeypatch.setattr(postprocess, "_ensure_tool_dict", lambda *_a, **_k: True)
    monkeypatch.setattr(postprocess, "latest_time", lambda _case: "1.0")
    monkeypatch.setattr(postprocess, "build_menu", _menu_sequence([1, 0]))
    monkeypatch.setattr(postprocess, "list_subkeys", lambda *_a, **_k: ["forces"])
    monkeypatch.setattr(postprocess, "_run_simple_tool", lambda *_a, **_k: run_cmds.append(list(_a[3])))
    postprocess.post_process_prompt(screen, case)
    assert run_cmds[-1] == ["postProcess", "-latestTime", "-funcs", "(forces)"]

    monkeypatch.setattr(postprocess, "build_menu", _menu_sequence([1, 3]))
    monkeypatch.setattr(postprocess, "list_subkeys", lambda *_a, **_k: [])
    monkeypatch.setattr(postprocess, "_show_message", lambda *_a, **_k: messages.append(_a[1]))
    postprocess.post_process_prompt(screen, case)
    assert "No functions found" in messages[-1]


def test_postprocess_manual_defaults_and_cancel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = tmp_path / "case"
    case.mkdir()
    run_cmds: list[list[str]] = []

    monkeypatch.setattr(postprocess, "_ensure_tool_dict", lambda *_a, **_k: True)
    monkeypatch.setattr(postprocess, "latest_time", lambda _case: "2.0")
    monkeypatch.setattr(postprocess, "build_menu", _menu_sequence([2]))
    monkeypatch.setattr(postprocess, "prompt_args_line", lambda *_a, **_k: [])
    monkeypatch.setattr(postprocess, "_run_simple_tool", lambda *_a, **_k: run_cmds.append(list(_a[3])))
    postprocess.post_process_prompt(_Screen(), case)
    assert run_cmds[-1] == ["postProcess", "-latestTime"]

    monkeypatch.setattr(postprocess, "build_menu", _menu_sequence([2]))
    monkeypatch.setattr(postprocess, "prompt_args_line", lambda *_a, **_k: None)
    postprocess.post_process_prompt(_Screen(), case)


def test_dictionary_compare_screen_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = tmp_path / "case"
    case.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    messages: list[str] = []
    shown: list[str] = []

    monkeypatch.setattr(diagnostics, "_show_message", lambda *_a, **_k: messages.append(_a[1]))
    monkeypatch.setattr(diagnostics, "_prompt_line", lambda *_a, **_k: "")
    diagnostics.dictionary_compare_screen(_Screen(), case)
    assert "No comparison path provided" in messages[-1]

    monkeypatch.setattr(diagnostics, "_prompt_line", lambda *_a, **_k: str(tmp_path / "missing"))
    diagnostics.dictionary_compare_screen(_Screen(), case)
    assert "Not a directory" in messages[-1]

    monkeypatch.setattr(diagnostics, "_prompt_line", lambda *_a, **_k: str(other))
    monkeypatch.setattr(diagnostics, "compare_case_dicts", lambda *_a, **_k: [])
    monkeypatch.setattr(diagnostics.Viewer, "display", lambda self: shown.append(self.content))
    diagnostics.dictionary_compare_screen(_Screen(), case)
    assert "No dictionary key differences" in shown[-1]


def test_diagnostics_screen_parallel_and_command_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    calls: list[str] = []
    shown: list[str] = []

    monkeypatch.setattr(diagnostics, "_no_foam_active", lambda: False)
    monkeypatch.setattr(diagnostics, "build_menu", _menu_sequence([4]))
    monkeypatch.setattr(
        diagnostics.run_tools,
        "parallel_consistency_screen",
        lambda *_a, **_k: calls.append("parallel"),
    )
    diagnostics.diagnostics_screen(_Screen(), case)
    assert calls == ["parallel"]

    monkeypatch.setattr(diagnostics, "build_menu", _menu_sequence([2]))
    monkeypatch.setattr(
        diagnostics,
        "run_trusted",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="ok", stderr=""),
    )
    monkeypatch.setattr(diagnostics, "_write_tool_log", lambda *_a, **_k: None)
    monkeypatch.setattr(diagnostics.Viewer, "display", lambda self: shown.append(self.content))
    diagnostics.diagnostics_screen(_Screen(), case)
    assert "foamSystemCheck" in shown[-1]

    monkeypatch.setattr(diagnostics, "build_menu", _menu_sequence([2]))
    monkeypatch.setattr(
        diagnostics,
        "run_trusted",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("missing")),
    )
    monkeypatch.setattr(diagnostics, "_show_message", lambda *_a, **_k: calls.append("error"))
    diagnostics.diagnostics_screen(_Screen(), case)
    assert calls[-1] == "error"


def test_shell_tools_job_status_script_and_rerun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = tmp_path / "case"
    case.mkdir()
    script = case / "run.sh"
    script.write_text("#!/bin/sh\necho ok\n")
    screen = _Screen(keys=[ord("h")])
    shown: list[str] = []
    run_shell: list[str] = []
    run_simple: list[list[str]] = []

    monkeypatch.setattr(shell_tools, "refresh_jobs", lambda *_a, **_k: [])
    monkeypatch.setattr(shell_tools, "key_in", lambda *_a, **_k: False)
    shell_tools.job_status_poll_screen(screen, case)
    assert screen.timeout_value == -1

    monkeypatch.setattr(shell_tools, "build_menu", _menu_sequence([0]))
    monkeypatch.setattr(
        shell_tools,
        "run_trusted",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="ok", stderr=""),
    )
    monkeypatch.setattr(shell_tools.Viewer, "display", lambda self: shown.append(self.content))
    shell_tools.run_shell_script_screen(_Screen(), case)
    assert "$ sh run.sh" in shown[-1]

    monkeypatch.setattr(shell_tools, "build_menu", _menu_sequence([0]))
    monkeypatch.setattr(shell_tools, "run_trusted", lambda *_a, **_k: (_ for _ in ()).throw(OSError("boom")))
    monkeypatch.setattr(shell_tools, "_show_message", lambda *_a, **_k: shown.append(_a[1]))
    shell_tools.run_shell_script_screen(_Screen(), case)
    assert "Failed to run" in shown[-1]

    monkeypatch.setattr(shell_tools, "get_last_tool_run", lambda: None)
    shell_tools.rerun_last_tool(_Screen(), case)
    assert "No previous tool run recorded." in shown[-1]

    monkeypatch.setattr(
        shell_tools,
        "get_last_tool_run",
        lambda: SimpleNamespace(name="demo", kind="simple", command=["echo", "ok"]),
    )
    monkeypatch.setattr(shell_tools, "_run_simple_tool", lambda *_a, **_k: run_simple.append(list(_a[3])))
    shell_tools.rerun_last_tool(_Screen(), case)
    assert run_simple[-1] == ["echo", "ok"]

    monkeypatch.setattr(
        shell_tools,
        "get_last_tool_run",
        lambda: SimpleNamespace(name="demo", kind="shell", command="echo ok"),
    )
    monkeypatch.setattr(shell_tools, "_run_shell_tool", lambda *_a, **_k: run_shell.append(str(_a[3])))
    shell_tools.rerun_last_tool(_Screen(), case)
    assert run_shell[-1] == "echo ok"


def test_time_pruner_validation_and_prune_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = tmp_path / "case"
    case.mkdir()
    t0 = case / "0"
    t1 = case / "1"
    t2 = case / "2"
    for path in (t0, t1, t2):
        path.mkdir()
        (path / "field").write_text("x\n")
    messages: list[str] = []

    monkeypatch.setattr(time_pruner, "_show_message", lambda *_a, **_k: messages.append(_a[1]))
    monkeypatch.setattr(time_pruner, "time_directories", lambda _case: [t0])
    time_pruner.time_directory_pruner_screen(_Screen(), case)
    assert "No time directories" in messages[-1]

    monkeypatch.setattr(time_pruner, "time_directories", lambda _case: [t0, t1, t2])
    monkeypatch.setattr(time_pruner, "prompt_line", lambda *_a, **_k: "bad")
    time_pruner.time_directory_pruner_screen(_Screen(), case)
    assert "Invalid number" in messages[-1]

    monkeypatch.setattr(time_pruner, "prompt_line", lambda *_a, **_k: "1")
    time_pruner.time_directory_pruner_screen(_Screen(), case)
    assert "Interval must be" in messages[-1]

    monkeypatch.setattr(time_pruner, "prompt_line", lambda *_a, **_k: "2")
    time_pruner.time_directory_pruner_screen(_Screen(), case)
    assert "Removed" in messages[-1]


def test_postprocessing_browser_sampling_and_presets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = tmp_path / "case"
    root = case / "postProcessing"
    root.mkdir(parents=True)
    output = root / "probe.dat"
    output.write_text("value\n")
    shown: list[str] = []
    messages: list[str] = []
    run_calls: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(postprocessing, "_show_message", lambda *_a, **_k: messages.append(_a[1]))
    monkeypatch.setattr(postprocessing, "build_menu", _menu_sequence([0]))
    monkeypatch.setattr(
        postprocessing.postprocessing_core,
        "collect_postprocessing_files",
        lambda *_a, **_k: [output],
    )
    monkeypatch.setattr(
        postprocessing.postprocessing_core,
        "postprocessing_summary",
        lambda *_a, **_k: ["Summary", "ok"],
    )
    monkeypatch.setattr(postprocessing.Viewer, "display", lambda self: shown.append(self.content))
    postprocessing.postprocessing_browser_screen(_Screen(), case)
    assert "Summary" in shown[-1]

    monkeypatch.setattr(postprocessing, "build_menu", _menu_sequence([1]))
    postprocessing.postprocessing_browser_screen(_Screen(), case)
    assert "value" in shown[-1]

    options = [
        SimpleNamespace(label="sample", enabled=False, required_path="system/sampleDict", command=["postProcess"]),
        SimpleNamespace(label="run", enabled=True, required_path=None, command=["postProcess", "-latestTime"]),
    ]
    monkeypatch.setattr(postprocessing.postprocessing_core, "sampling_options", lambda *_a, **_k: options)
    monkeypatch.setattr(postprocessing, "build_menu", _menu_sequence([0]))
    postprocessing.sampling_sets_screen(_Screen(), case)
    assert "Missing" in messages[-1]

    monkeypatch.setattr(postprocessing, "build_menu", _menu_sequence([1]))
    monkeypatch.setattr(
        postprocessing,
        "run_tool_command",
        lambda *_a, **_k: run_calls.append((_a[2], list(_a[3]))),
    )
    postprocessing.sampling_sets_screen(_Screen(), case)
    assert run_calls[-1][0] == "run"

    presets_path = case / "ofti.parametric"
    presets_path.write_text("demo|system/controlDict|application|simpleFoam\n")
    monkeypatch.setattr(
        postprocessing.postprocessing_core,
        "read_parametric_presets",
        lambda *_a, **_k: ([SimpleNamespace(name="demo", dict_path="system/controlDict", entry="application", values=["simpleFoam"])], []),
    )
    monkeypatch.setattr(postprocessing, "build_menu", _menu_sequence([0]))
    monkeypatch.setattr(postprocessing, "_prompt_line", lambda *_a, **_k: "y")
    monkeypatch.setattr(postprocessing, "build_parametric_cases", lambda *_a, **_k: [case / "case_1"])
    monkeypatch.setattr(postprocessing, "run_cases", lambda *_a, **_k: [case / "case_1"])
    postprocessing.parametric_presets_screen(_Screen(), case)
    assert "Failures" in shown[-1]


def test_parametric_helpers_and_screen_error_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    (case / "ofti.parametric").write_text("demo|system/controlDict|application|simpleFoam\n")
    shown: list[str] = []
    messages: list[str] = []

    monkeypatch.setattr(
        parametric_tools.postprocessing_core,
        "read_parametric_presets",
        lambda *_a, **_k: ([], ["bad preset"]),
    )
    monkeypatch.setattr(parametric_tools, "_show_message", lambda *_a, **_k: messages.append(_a[1]))
    monkeypatch.setattr(parametric_tools, "_parametric_form", lambda *_a, **_k: None)
    parametric_tools.foamlib_parametric_study_screen(_Screen(), case)
    assert "falling back to manual input" in messages[-1]

    monkeypatch.setattr(
        parametric_tools.postprocessing_core,
        "read_parametric_presets",
        lambda *_a, **_k: ([SimpleNamespace(name="demo", dict_path="system/controlDict", entry="application", values=["simpleFoam"])], []),
    )
    monkeypatch.setattr(parametric_tools, "build_menu", lambda *_a, **_k: _OneChoiceMenu(0))
    monkeypatch.setattr(
        parametric_tools,
        "_parametric_form",
        lambda *_a, **_k: ("system/controlDict", "application", ["simpleFoam"], True),
    )
    monkeypatch.setattr(
        parametric_tools,
        "build_parametric_cases",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad setup")),
    )
    parametric_tools.foamlib_parametric_study_screen(_Screen(), case)
    assert "Parametric setup failed" in messages[-1]

    monkeypatch.setattr(parametric_tools, "build_parametric_cases", lambda *_a, **_k: [case / "variant"])
    monkeypatch.setattr(parametric_tools, "run_cases", lambda *_a, **_k: [case / "variant"])
    monkeypatch.setattr(parametric_tools.Viewer, "display", lambda self: shown.append(self.content))
    parametric_tools.foamlib_parametric_study_screen(_Screen(), case)
    assert "Failures:" in shown[-1]

    assert parametric_tools._finalize_parametric(_Screen(), "system/controlDict", "", ["a"], False) is None
    assert parametric_tools._finalize_parametric(_Screen(), "system/controlDict", "entry", [], False) is None
    ok = parametric_tools._finalize_parametric(
        _Screen(),
        "system/controlDict",
        "entry",
        ["a"],
        False,
    )
    assert ok == ("system/controlDict", "entry", ["a"], False)

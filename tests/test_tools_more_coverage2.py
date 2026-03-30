from __future__ import annotations

import types
from pathlib import Path
from typing import Any, cast

import pytest

from ofti.tools import diagnostics, postprocessing, shell_tools, solver


class _Screen:
    def __init__(self, keys: list[int] | None = None, height: int = 24, width: int = 100) -> None:
        self._keys = list(keys or [ord("h")])
        self.height = height
        self.width = width
        self.lines: list[str] = []
        self.timeout_value = -1

    def clear(self) -> None:
        self.lines.clear()

    def addstr(self, *args: object) -> None:
        self.lines.append(str(args[-1]))

    def refresh(self) -> None:
        return None

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("h")

    def timeout(self, value: int) -> None:
        self.timeout_value = value

    def getmaxyx(self) -> tuple[int, int]:
        return (self.height, self.width)

    def getyx(self) -> tuple[int, int]:
        return (0, 0)

    def attron(self, *_args: object) -> None:
        return None

    def attroff(self, *_args: object) -> None:
        return None

    def move(self, *_args: object) -> None:
        return None

    def clrtoeol(self) -> None:
        return None


class _Menu:
    def __init__(self, choice: int) -> None:
        self._choice = choice

    def navigate(self) -> int:
        return self._choice


def test_postprocessing_browser_and_presets_branches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen()
    shown: list[str] = []
    viewed: list[str] = []

    monkeypatch.setattr(postprocessing, "_show_message", lambda _s, text: shown.append(text))
    postprocessing.postprocessing_browser_screen(screen, case)
    assert "postProcessing directory not found." in shown[-1]

    root = case / "postProcessing"
    root.mkdir()
    monkeypatch.setattr(postprocessing.postprocessing_core, "collect_postprocessing_files", lambda _root: [])
    postprocessing.postprocessing_browser_screen(screen, case)
    assert "No postProcessing files found." in shown[-1]

    sample = root / "probe.dat"
    sample.write_text("1 2 3\n")
    monkeypatch.setattr(postprocessing.postprocessing_core, "collect_postprocessing_files", lambda _root: [sample])
    monkeypatch.setattr(postprocessing, "build_menu", lambda *_a, **_k: _Menu(0))

    class _Viewer:
        def __init__(self, _s: object, text: str) -> None:
            viewed.append(text)

        def display(self) -> None:
            return None

    monkeypatch.setattr(postprocessing, "Viewer", _Viewer)
    monkeypatch.setattr(postprocessing.postprocessing_core, "postprocessing_summary", lambda _root: ["sum"])
    postprocessing.postprocessing_browser_screen(screen, case)
    assert viewed and "sum" in viewed[-1]

    monkeypatch.setattr(postprocessing, "build_menu", lambda *_a, **_k: _Menu(1))
    monkeypatch.setattr(Path, "read_text", lambda *_a, **_k: (_ for _ in ()).throw(OSError("boom")))
    postprocessing.postprocessing_browser_screen(screen, case)
    assert "Failed to read probe.dat" in shown[-1]

    monkeypatch.setattr(postprocessing, "build_menu", lambda *_a, **_k: _Menu(2))
    monkeypatch.setattr(postprocessing.postprocessing_core, "collect_postprocessing_files", lambda _root: [sample])
    postprocessing.postprocessing_browser_screen(screen, case)

    monkeypatch.setattr(postprocessing, "prompt_line", lambda *_a, **_k: None)
    assert postprocessing._prompt_line(screen, "x") == ""


def test_postprocessing_sampling_and_parametric_error_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen()
    shown: list[str] = []
    viewed: list[str] = []

    monkeypatch.setattr(postprocessing, "_show_message", lambda _s, text: shown.append(text))
    options = [
        types.SimpleNamespace(label="sample", enabled=False, command=["postProcess"], required_path="system/sampleDict"),
    ]
    monkeypatch.setattr(postprocessing.postprocessing_core, "sampling_options", lambda _case: options)
    monkeypatch.setattr(postprocessing, "build_menu", lambda *_a, **_k: _Menu(0))
    postprocessing.sampling_sets_screen(screen, case)
    assert "Missing system/sampleDict." in shown[-1]

    monkeypatch.setattr(postprocessing, "build_menu", lambda *_a, **_k: _Menu(1))
    postprocessing.sampling_sets_screen(screen, case)

    postprocessing.parametric_presets_screen(screen, case)
    assert "ofti.parametric not found" in shown[-1]

    presets = case / "ofti.parametric"
    presets.write_text("demo | system/controlDict | application | simpleFoam\n")

    class _Viewer:
        def __init__(self, _s: object, text: str) -> None:
            viewed.append(text)

        def display(self) -> None:
            return None

    monkeypatch.setattr(postprocessing, "Viewer", _Viewer)
    monkeypatch.setattr(postprocessing.postprocessing_core, "read_parametric_presets", lambda _p: ([], ["bad line"]))
    postprocessing.parametric_presets_screen(screen, case)
    assert "PARAMETRIC PRESET ERRORS" in viewed[-1]

    monkeypatch.setattr(postprocessing.postprocessing_core, "read_parametric_presets", lambda _p: ([], []))
    postprocessing.parametric_presets_screen(screen, case)
    assert "No presets found in ofti.parametric." in shown[-1]

    preset = types.SimpleNamespace(name="demo", dict_path="system/controlDict", entry="application", values=["simpleFoam"])
    monkeypatch.setattr(postprocessing.postprocessing_core, "read_parametric_presets", lambda _p: ([preset], []))
    monkeypatch.setattr(postprocessing, "build_menu", lambda *_a, **_k: _Menu(1))
    postprocessing.parametric_presets_screen(screen, case)

    monkeypatch.setattr(postprocessing, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(postprocessing, "prompt_line", lambda *_a, **_k: "y")
    monkeypatch.setattr(postprocessing, "build_parametric_cases", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad preset")))
    postprocessing.parametric_presets_screen(screen, case)
    assert "Parametric setup failed: bad preset" in shown[-1]

    monkeypatch.setattr(postprocessing, "build_parametric_cases", lambda *_a, **_k: [case])
    monkeypatch.setattr(postprocessing, "run_cases", lambda *_a, **_k: [])
    postprocessing.parametric_presets_screen(screen, case)
    assert "All cases completed." in viewed[-1]


def test_diagnostics_case_report_compare_and_menu(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    screen = _Screen()
    shown: list[str] = []
    viewed: list[str] = []
    parallel_calls: list[bool] = []
    original_prompt = diagnostics._prompt_line

    class _Viewer:
        def __init__(self, _s: object, text: str) -> None:
            viewed.append(text)

        def display(self) -> None:
            return None

    monkeypatch.setattr(diagnostics, "Viewer", _Viewer)
    monkeypatch.setattr(diagnostics, "detect_solver", lambda _c: "simpleFoam")
    monkeypatch.setattr(diagnostics, "detect_parallel_settings", lambda _c: "4")
    monkeypatch.setattr(diagnostics, "latest_time", lambda _c: "10")
    monkeypatch.setattr(diagnostics, "detect_mesh_stats", lambda _c: "ok")
    monkeypatch.setattr(diagnostics, "mesh_counts", lambda _c: (100, 200, 300))
    monkeypatch.setattr(diagnostics, "_directory_size", lambda _c: 2048)
    diagnostics.case_report_screen(screen, case)
    assert "Mesh counts: cells=100, faces=200, points=300" in viewed[-1]

    monkeypatch.setattr(diagnostics, "_show_message", lambda _s, text: shown.append(text))
    monkeypatch.setattr(diagnostics, "_prompt_line", lambda *_a, **_k: "")
    diagnostics.dictionary_compare_screen(screen, case)
    assert "No comparison path provided." in shown[-1]

    monkeypatch.setattr(diagnostics, "_prompt_line", lambda *_a, **_k: str(case / "missing"))
    diagnostics.dictionary_compare_screen(screen, case)
    assert "Not a directory" in shown[-1]

    monkeypatch.setattr(diagnostics, "_prompt_line", lambda *_a, **_k: str(other))
    monkeypatch.setattr(
        diagnostics,
        "compare_case_dicts",
        lambda *_a, **_k: [
            types.SimpleNamespace(rel_path="constant/a", error="parse", missing_in_left=[], missing_in_right=[]),
            types.SimpleNamespace(rel_path="constant/b", error=None, missing_in_left=["x"], missing_in_right=["y"]),
        ],
    )
    diagnostics.dictionary_compare_screen(screen, case)
    assert "missing in current: x" in viewed[-1]

    monkeypatch.setattr(diagnostics, "_no_foam_active", lambda: True)
    monkeypatch.setattr(diagnostics, "build_menu", lambda *_a, **_k: _Menu(-1))
    diagnostics.diagnostics_screen(screen, case)

    monkeypatch.setattr(diagnostics, "_no_foam_active", lambda: False)
    monkeypatch.setattr(diagnostics, "build_menu", lambda *_a, **_k: _Menu(0))
    monkeypatch.setattr(diagnostics, "case_report_screen", lambda *_a, **_k: parallel_calls.append(True))
    diagnostics.diagnostics_screen(screen, case)

    monkeypatch.setattr(diagnostics, "build_menu", lambda *_a, **_k: _Menu(1))
    monkeypatch.setattr(diagnostics, "dictionary_compare_screen", lambda *_a, **_k: parallel_calls.append(True))
    diagnostics.diagnostics_screen(screen, case)

    monkeypatch.setattr(diagnostics, "build_menu", lambda *_a, **_k: _Menu(4))
    monkeypatch.setattr(diagnostics.run_tools, "parallel_consistency_screen", lambda *_a, **_k: parallel_calls.append(True))
    diagnostics.diagnostics_screen(screen, case)

    monkeypatch.setattr(diagnostics, "build_menu", lambda *_a, **_k: _Menu(2))
    monkeypatch.setattr(diagnostics, "run_trusted", lambda *_a, **_k: (_ for _ in ()).throw(OSError("boom")))
    diagnostics.diagnostics_screen(screen, case)
    assert "Failed to run foamSystemCheck" in shown[-1]
    monkeypatch.setattr(diagnostics, "prompt_line", lambda *_a, **_k: None)
    assert original_prompt(screen, "x") == ""


def test_diagnostics_directory_size_error_and_human_size(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    bad = case / "bad.txt"
    bad.write_text("x")

    class _BadPath:
        def is_file(self) -> bool:
            return True

        def stat(self) -> Any:
            raise OSError("x")

    monkeypatch.setattr(Path, "rglob", lambda *_a, **_k: [_BadPath()])
    assert diagnostics._directory_size(case) == 0
    assert diagnostics._human_size(5 * 1024**4).endswith("TB")


def test_shell_tools_job_status_and_back_choice(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen(keys=[ord("x")], height=2)

    monkeypatch.setattr(
        shell_tools,
        "refresh_jobs",
        lambda _c: [{"name": "solver", "pid": 1, "status": "running", "log": "log.simpleFoam", "started_at": 1.0}],
    )
    monkeypatch.setattr(shell_tools, "key_in", lambda _k, keys: bool(keys))
    monkeypatch.setattr(shell_tools, "get_config", lambda: types.SimpleNamespace(keys={"quit": [ord("x")], "back": [ord("b")] }))
    shell_tools.job_status_poll_screen(screen, case)
    assert screen.timeout_value == -1

    back_screen = _Screen(keys=[ord("b")])
    monkeypatch.setattr(shell_tools, "key_in", lambda key, keys: key in set(keys))
    monkeypatch.setattr(shell_tools, "get_config", lambda: types.SimpleNamespace(keys={"quit": [], "back": [ord("b")] }))
    shell_tools.job_status_poll_screen(back_screen, case)

    script = case / "run.sh"
    script.write_text("echo ok\n")
    monkeypatch.setattr(shell_tools, "build_menu", lambda *_a, **_k: _Menu(1))
    shell_tools.run_shell_script_screen(screen, case)


def test_solver_live_paths_and_zero_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen(keys=[ord("n"), ord("y"), ord("h")])
    shown: list[str] = []
    called: list[str] = []
    original_ensure_zero_dir = solver._ensure_zero_dir

    monkeypatch.setattr(solver, "_show_message", lambda _s, text: shown.append(text))
    monkeypatch.setattr(solver, "resolve_solver_name", lambda _c: (None, "no solver"))
    solver.run_current_solver_live(screen, case)
    assert shown[-1] == "no solver"

    monkeypatch.setattr(solver, "resolve_solver_name", lambda _c: (None, None))
    solver.run_current_solver_live(screen, case)
    assert "Could not determine solver name." in shown[-1]

    monkeypatch.setattr(solver, "resolve_solver_name", lambda _c: ("simpleFoam", None))
    monkeypatch.setattr(solver, "_ensure_zero_dir", lambda *_a, **_k: False)
    solver.run_current_solver_live(screen, case)

    monkeypatch.setattr(solver, "_ensure_zero_dir", lambda *_a, **_k: True)
    monkeypatch.setattr(solver, "validate_initial_fields", lambda _c: ["missing 0/U"])
    solver.run_current_solver_live(screen, case)
    assert "Cannot run solver:" in shown[-1]

    monkeypatch.setattr(solver, "validate_initial_fields", lambda _c: [])
    monkeypatch.setattr(solver, "resolve_openfoam_bashrc", lambda: "/etc/bashrc")
    monkeypatch.setattr(solver, "_run_solver_live_shell", lambda *_a, **_k: called.append("shell"))
    (case / "log.simpleFoam").write_text("old\n")
    monkeypatch.setattr(solver, "remove_empty_log", lambda _p: True)
    solver.run_current_solver_live(screen, case)
    assert called[-1] == "shell"

    # zero-dir helper branches
    monkeypatch.setattr(solver, "_ensure_zero_dir", original_ensure_zero_dir)
    zero_orig = case / "0.orig"
    zero_orig.mkdir(exist_ok=True)
    (zero_orig / "U").write_text("u\n")
    assert solver._ensure_zero_dir(_Screen(keys=[ord("n")]), case) is False
    monkeypatch.setattr(solver.shutil, "copytree", lambda *_a, **_k: (_ for _ in ()).throw(OSError("copy failed")))
    assert solver._ensure_zero_dir(_Screen(keys=[ord("y")]), case) is False
    assert "Failed to copy 0.orig -> 0" in shown[-1]

    monkeypatch.setattr(solver.shutil, "copytree", lambda _src, dst, **_k: Path(dst).mkdir())
    assert solver._ensure_zero_dir(_Screen(keys=[ord("y")]), case) is True
    empty_case = tmp_path / "empty-case"
    empty_case.mkdir()
    assert solver._ensure_zero_dir(_Screen(keys=[ord("n")]), empty_case) is True


def test_solver_run_live_shell_cmd_and_tail_finish(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    screen = _Screen(keys=[ord("h")], height=2)
    shown: list[str] = []
    tailed: list[str] = []
    original_tail = solver._tail_process_log

    monkeypatch.setattr(solver, "_show_message", lambda _s, text: shown.append(text))
    monkeypatch.setattr(solver, "_expand_shell_command", lambda cmd, _c: cmd)
    monkeypatch.setattr(
        solver.watch_service,
        "start_payload",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bash missing")),
    )
    solver._run_solver_live_shell(screen, case, "simpleFoam", "simpleFoam")
    assert "Failed to run simpleFoam" in shown[-1]

    monkeypatch.setattr(
        solver.watch_service,
        "start_payload",
        lambda *_a, **_k: {"pid": 55, "job_id": "job-1"},
    )
    monkeypatch.setattr(solver, "_tail_process_log", lambda *_a, **_k: tailed.append("ok"))
    solver._run_solver_live_shell(screen, case, "simpleFoam", "simpleFoam")
    solver._run_solver_live_cmd(screen, case, "simpleFoam", ["simpleFoam"])
    assert tailed == ["ok", "ok"]
    monkeypatch.setattr(solver, "_tail_process_log", original_tail)

    class _Finished:
        def poll(self) -> int:
            return 2

        def terminate(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> None:
            _ = timeout

    finished: list[tuple[str | None, str, int | None]] = []
    monkeypatch.setattr(solver, "read_log_tail_lines", lambda *_a, **_k: (_ for _ in ()).throw(OSError("x")))
    monkeypatch.setattr(solver, "finish_job", lambda _c, job_id, status, rc: finished.append((job_id, status, rc)))
    monkeypatch.setattr(solver, "fatal_log_line", lambda _lines: "FATAL: boom")
    monkeypatch.setattr(solver, "residual_spark_lines", lambda _lines, _width: ["res"])
    solver._tail_process_log(
        screen,
        case,
        "simpleFoam",
        cast("Any", _Finished()),
        case / "log.simpleFoam",
        "job-9",
    )
    assert finished[-1] == ("job-9", "finished", 2)
    assert screen.timeout_value == -1

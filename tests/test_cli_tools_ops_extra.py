from __future__ import annotations

import os
import subprocess
import types
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from ofti.tools import case_source_service, knife_service, watch_service
from ofti.tools.cli_tools import common, knife, run, watch


def _make_case(path: Path, solver: str = "simpleFoam") -> Path:
    (path / "system").mkdir(parents=True)
    (path / "0").mkdir()
    (path / "system" / "controlDict").write_text(f"application {solver};\n")
    return path


def test_common_require_case_dir_and_read_text_errors(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        common.require_case_dir(tmp_path / "missing")

    case = _make_case(tmp_path / "case")
    with pytest.raises(ValueError):
        common.read_text(case)


def test_common_resolve_log_source_fallbacks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _make_case(tmp_path / "case")
    solver_log = case / "log.simpleFoam"
    solver_log.write_text("solver\n")
    monkeypatch.setattr(case_source_service, "resolve_solver_name", lambda _case: ("simpleFoam", None))
    assert common.resolve_log_source(case) == solver_log.resolve()

    monkeypatch.setattr(case_source_service, "resolve_solver_name", lambda _case: (None, "no solver"))
    solver_log.unlink()
    old_log = case / "log.old"
    new_log = case / "log.new"
    old_log.write_text("old\n")
    new_log.write_text("new\n")
    os.utime(old_log, ns=(1_000_000_000, 1_000_000_000))
    os.utime(new_log, ns=(2_000_000_000, 2_000_000_000))
    assert common.resolve_log_source(case) == new_log.resolve()

    empty_case = _make_case(tmp_path / "empty-case")
    monkeypatch.setattr(case_source_service, "resolve_solver_name", lambda _case: (None, "no solver"))
    with pytest.raises(ValueError, match="no log\\.\\* files found"):
        common.resolve_log_source(empty_case)


def test_run_resolve_tool_normalized_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.setattr(
        run,
        "tool_catalog",
        lambda _case: [("Plot:Residuals", ["python", "plot.py"])],
    )
    assert run.resolve_tool(case, " plot: residuals ") == ("Plot:Residuals", ["python", "plot.py"])
    assert run.resolve_tool(case, "missing") is None


def test_run_solver_command_validates_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _make_case(tmp_path / "case")

    monkeypatch.setattr(run, "resolve_solver_name", lambda _case: (None, "missing application"))
    with pytest.raises(ValueError, match="Cannot resolve solver: missing application"):
        run.solver_command(case)

    monkeypatch.setattr(run, "resolve_solver_name", lambda _case: (None, None))
    with pytest.raises(ValueError, match="Cannot resolve solver from case"):
        run.solver_command(case)

    monkeypatch.setattr(run, "resolve_solver_name", lambda _case: ("simpleFoam", None))
    monkeypatch.setattr(run, "validate_initial_fields", lambda _case: ["missing 0/U"])
    with pytest.raises(ValueError, match="missing 0/U"):
        run.solver_command(case)


def test_run_solver_command_parallel_modes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _make_case(tmp_path / "case")
    (case / "system" / "decomposeParDict").write_text("numberOfSubdomains 4;\n")
    monkeypatch.setattr(run, "validate_initial_fields", lambda _case: [])

    display, cmd = run.solver_command(case, solver="simpleFoam", parallel=4, mpi="mpirun")
    assert display == "simpleFoam-parallel"
    assert cmd == ["mpirun", "-np", "4", "simpleFoam", "-parallel"]

    monkeypatch.setattr(run, "detect_mpi_launcher", lambda: None)
    with pytest.raises(ValueError, match="MPI launcher not found"):
        run.solver_command(case, solver="simpleFoam", parallel=2)


def test_run_solver_command_parallel_syncs_number_of_subdomains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    decompose = case / "system" / "decomposeParDict"
    decompose.write_text("numberOfSubdomains 6;\n")
    monkeypatch.setattr(run, "validate_initial_fields", lambda _case: [])
    monkeypatch.setattr(run, "detect_mpi_launcher", lambda: "mpirun")

    display, cmd = run.solver_command(case, solver="simpleFoam", parallel=2)

    assert display == "simpleFoam-parallel"
    assert cmd == ["mpirun", "-np", "2", "simpleFoam", "-parallel"]
    assert "numberOfSubdomains 2;" in decompose.read_text()


def test_run_solver_command_parallel_requires_decompose_dict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.setattr(run, "validate_initial_fields", lambda _case: [])
    with pytest.raises(ValueError, match="Missing system/decomposeParDict"):
        run.solver_command(case, solver="simpleFoam", parallel=2, mpi="mpirun")


def test_run_solver_command_parallel_reports_actionable_sync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    decompose = case / "system" / "decomposeParDict"
    decompose.write_text("numberOfSubdomains 6;\n")
    monkeypatch.setattr(run, "validate_initial_fields", lambda _case: [])
    monkeypatch.setattr(run, "detect_mpi_launcher", lambda: "mpirun")
    monkeypatch.setattr(run, "write_entry", lambda *_a, **_k: True)
    monkeypatch.setattr(run, "_write_subdomains_fallback", lambda *_a, **_k: False)

    with pytest.raises(ValueError, match="Parallel launch blocked: requested 2 ranks"):
        run.solver_command(case, solver="simpleFoam", parallel=2, mpi="mpirun")


def test_run_solver_command_parallel_no_sync_fails_fast_with_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    decompose = case / "system" / "decomposeParDict"
    decompose.write_text("numberOfSubdomains 6;\n")
    monkeypatch.setattr(run, "validate_initial_fields", lambda _case: [])

    with pytest.raises(ValueError, match="Run with --sync-subdomains"):
        run.solver_command(case, solver="simpleFoam", parallel=2, sync_subdomains=False)


def test_run_execute_case_command_foreground_unsets_shell_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    captured: dict[str, object] = {}
    monkeypatch.setenv("BASH_ENV", "x")
    monkeypatch.setenv("ENV", "y")

    def fake_run_trusted(argv: list[str], **kwargs: object) -> object:
        captured["argv"] = argv
        captured.update(kwargs)
        return types.SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(run, "run_trusted", fake_run_trusted)

    result = run.execute_case_command(case, "simpleFoam", ["simpleFoam"], background=False)

    assert result.returncode == 0
    assert result.stdout == "ok\n"
    env = captured["env"]
    assert isinstance(env, dict)
    assert "BASH_ENV" not in env
    assert "ENV" not in env


def test_run_execute_case_command_background_registers_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    seen: dict[str, object] = {}

    class FakePopen:
        def __init__(self, argv: list[str], **kwargs: object) -> None:
            self.pid = 4242
            seen["argv"] = argv
            seen.update(kwargs)

    def fake_register_job(
        case_path: Path,
        name: str,
        pid: int,
        shell_cmd: str,
        log_path: Path,
    ) -> None:
        seen["case_path"] = case_path
        seen["name"] = name
        seen["pid"] = pid
        seen["shell_cmd"] = shell_cmd
        seen["log_path"] = log_path

    monkeypatch.setattr(run.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(run, "register_job", fake_register_job)

    result = run.execute_case_command(case, "tool with spaces!", ["echo", "hi"], background=True)

    assert result.pid == 4242
    assert result.log_path is not None
    assert result.log_path.name == "log.toolwithspaces"
    assert seen["log_path"] == result.log_path
    stdout = seen["stdout"]
    assert hasattr(stdout, "closed")
    assert stdout.closed is True


def test_run_prepare_parallel_case_dry_run_and_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    (case / "processor0").mkdir()
    (case / "processor1").mkdir()
    seen: dict[str, object] = {}

    def _exec(*_a: object, **kwargs: object) -> run.RunResult:
        seen["kwargs"] = kwargs
        return run.RunResult(0, "", "", pid=None, log_path=None)

    monkeypatch.setattr(run, "execute_case_command", _exec)

    dry = run.prepare_parallel_case(case, parallel=2, clean_processors=True, dry_run=True)
    assert dry["clean_processors"] is True
    assert len(cast("list[str]", dry["cleaned_processors"])) == 2
    assert (case / "processor0").is_dir()

    applied = run.prepare_parallel_case(case, parallel=2, clean_processors=True, dry_run=False)
    assert applied["decompose_returncode"] == 0
    assert not (case / "processor0").exists()
    assert not (case / "processor1").exists()
    kwargs = cast("dict[str, object]", seen["kwargs"])
    assert kwargs["background"] is False


def test_run_prepare_parallel_case_reports_decompose_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.setattr(
        run,
        "execute_case_command",
        lambda *_a, **_k: run.RunResult(1, "", "bad decompose", pid=None, log_path=None),
    )
    with pytest.raises(ValueError, match="decomposePar failed"):
        run.prepare_parallel_case(case, parallel=2, clean_processors=False, dry_run=False)


def test_run_detect_mpi_launcher_tries_multiple(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_resolve(candidate: str) -> str:
        seen.append(candidate)
        if candidate == "mpirun":
            raise FileNotFoundError(candidate)
        return "/usr/bin/mpiexec"

    monkeypatch.setattr(run, "resolve_executable", fake_resolve)
    assert run.detect_mpi_launcher() == "/usr/bin/mpiexec"
    assert seen == ["mpirun", "mpiexec"]


def test_knife_preflight_uses_fallback_solver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _make_case(tmp_path / "case")
    (case / "constant" / "polyMesh").mkdir(parents=True)
    (case / "constant" / "polyMesh" / "boundary").write_text("ok\n")

    monkeypatch.setattr(knife_service, "resolve_solver_name", lambda _case: (None, "missing solver"))
    monkeypatch.setattr(knife_service.shutil, "which", lambda _name: None)
    monkeypatch.delenv("WM_PROJECT_DIR", raising=False)

    payload = knife.preflight_payload(case)
    assert payload["ok"] is True
    assert payload["solver"] == "simpleFoam"
    assert payload["solver_error"] is None


def test_knife_set_entry_payload_missing_file_raises(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "case")
    with pytest.raises(ValueError, match="dictionary not found"):
        knife.set_entry_payload(case, "system/missingDict", "k", "v")


def test_knife_proc_helpers(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "case")
    proc_dir = tmp_path / "proc" / "123"
    proc_dir.mkdir(parents=True)
    case_arg = str((tmp_path / "demo-case").resolve())
    (proc_dir / "cmdline").write_bytes(f"/usr/bin/simpleFoam\x00-case\x00{case_arg}\x00".encode())
    (proc_dir / "cwd").symlink_to(case, target_is_directory=True)

    args = knife._read_proc_args(proc_dir)
    assert args == ["/usr/bin/simpleFoam", "-case", case_arg]
    assert knife._args_match_solver(args, "simpleFoam") is True
    assert knife._targets_case(proc_dir, ["/usr/bin/simpleFoam"], case) is True

    assert knife._running_job_pids(
        [{"pid": 1}, {"pid": 0}, {"pid": "bad"}, {"pid": -2}, {"pid": 7}],
    ) == [1, 7]


def test_knife_scan_proc_solver_processes(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "case")
    proc_root = tmp_path / "proc"
    proc_root.mkdir()

    tracked = proc_root / "100"
    tracked.mkdir()
    (tracked / "cmdline").write_bytes(b"simpleFoam\x00-case\x00.\x00")
    (tracked / "cwd").symlink_to(case, target_is_directory=True)

    solver_proc = proc_root / "200"
    solver_proc.mkdir()
    (solver_proc / "cmdline").write_bytes(b"/opt/simpleFoam\x00-case\x00.\x00")
    (solver_proc / "cwd").symlink_to(case, target_is_directory=True)

    unrelated = proc_root / "300"
    unrelated.mkdir()
    (unrelated / "cmdline").write_bytes(b"rhoSimpleFoam\x00")
    (unrelated / "cwd").symlink_to(case, target_is_directory=True)

    found = knife._scan_proc_solver_processes(
        case,
        "simpleFoam",
        tracked_pids={100},
        proc_root=proc_root,
    )

    assert [row["pid"] for row in found] == [200]
    assert found[0]["solver"] == "simpleFoam"


def test_watch_stop_payload_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.setattr(
        watch_service,
        "refresh_jobs",
        lambda _case: [
            {"id": "1", "name": "solverA", "pid": 11, "status": "running"},
            {"id": "2", "name": "solverB", "pid": "bad", "status": "running"},
            {"id": "3", "name": "solverC", "pid": 33, "status": "running"},
        ],
    )

    finished: list[tuple[str, str]] = []
    killed: list[int] = []

    def fake_finish(_case: Path, job_id: str, status: str, _rc: int | None) -> None:
        finished.append((job_id, status))

    def fake_kill(pid: int, _sig: int) -> None:
        killed.append(pid)
        if pid == 33:
            raise OSError("gone")

    monkeypatch.setattr(watch_service, "finish_job", fake_finish)
    monkeypatch.setattr(watch_service.os, "kill", fake_kill)

    payload = watch.stop_payload(case, all_jobs=True)

    assert payload["selected"] == 3
    assert [row["id"] for row in payload["stopped"]] == ["1"]
    assert {row["id"] for row in payload["failed"]} == {"2", "3"}
    assert ("1", "stopped") in finished
    assert ("3", "missing") in finished
    assert killed == [11, 33]


def test_watch_log_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _make_case(tmp_path / "case")
    log_path = case / "log.simpleFoam"
    log_path.write_text("a\nb\nc\n")

    monkeypatch.setattr(watch_service.case_source_service, "resolve_log_source", lambda source: source)
    tail = watch.log_tail_payload(log_path, lines=2)
    assert tail["lines"] == ["b", "c"]
    assert watch.log_tail_payload(log_path, lines=0)["lines"] == []

    jobs = [
        {"id": "x", "log": "log.simpleFoam"},
    ]
    monkeypatch.setattr(watch_service, "load_jobs", lambda _case: jobs)
    by_job = watch.log_tail_payload_for_job(case, job_id="x", lines=1)
    assert by_job["lines"] == ["c"]

    with pytest.raises(ValueError, match="job not found"):
        watch_service._log_path_from_job(case, "missing")


def _write_proc_entry(proc_root: Path, pid: int, ppid: int, cmdline: bytes, cwd: Path) -> None:
    proc_dir = proc_root / str(pid)
    proc_dir.mkdir()
    (proc_dir / "cmdline").write_bytes(cmdline)
    (proc_dir / "stat").write_text(f"{pid} (cmd) S {ppid} 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n")
    (proc_dir / "cwd").symlink_to(cwd, target_is_directory=True)


def test_knife_scan_proc_detects_mpi_launcher_and_rank_processes(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "case", solver="hy2Foam")
    proc_root = tmp_path / "proc"
    proc_root.mkdir()

    _write_proc_entry(proc_root, 10, 1, b"mpirun\x00-np\x004\x00hy2Foam\x00-case\x00.\x00", case)
    _write_proc_entry(proc_root, 11, 10, b"hy2Foam\x00-parallel\x00-case\x00.\x00", case)
    _write_proc_entry(proc_root, 12, 10, b"hy2Foam\x00-parallel\x00-case\x00.\x00", case)

    rows = knife._scan_proc_solver_processes(
        case,
        "hy2Foam",
        tracked_pids={11},
        proc_root=proc_root,
        include_tracked=True,
    )

    by_pid = {int(row["pid"]): row for row in rows}
    assert by_pid[10]["role"] == "launcher"
    assert by_pid[11]["tracked"] is True
    assert by_pid[12]["tracked"] is False


def test_knife_status_payload_includes_runtime_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _make_case(tmp_path / "case")
    control = case / "system" / "controlDict"
    control.write_text(
        "\n".join(
            [
                "application simpleFoam;",
                "startTime 0;",
                "endTime 100;",
                "residualTolerance 1e-06;",
            ],
        ),
    )
    log = case / "log.simpleFoam"
    log.write_text(
        "\n".join(
            [
                "Time = 1",
                "deltaT = 0.01",
                "ExecutionTime = 2 s",
                "Time = 2",
                "deltaT = 0.02",
                "ExecutionTime = 5 s",
                "residualTolerance satisfied",
            ],
        ),
    )

    monkeypatch.setattr(knife_service, "resolve_solver_name", lambda _case: ("simpleFoam", None))
    monkeypatch.setattr(knife_service, "refresh_jobs", lambda _case: [])
    monkeypatch.setattr(
        knife_service,
        "_scan_proc_solver_processes",
        lambda *_args, **_kwargs: [],
    )

    payload = knife.status_payload(case)

    assert payload["latest_time"] == 2.0
    assert payload["latest_delta_t"] == 0.02
    assert payload["run_time_control"]["criteria"][0]["key"] == "residualTolerance"
    assert payload["run_time_control"]["passed"] == 1
    assert payload["running"] is True


def test_knife_converge_payload_strict(tmp_path: Path) -> None:
    log = tmp_path / "log.hy2Foam"
    log.write_text(
        "\n".join(
            [
                "Time = 1",
                "shockPosition = 0.50",
                "Cd = 0.200",
                "time step continuity errors : sum local = 1e-8, global = 1e-5, cumulative = 1e-3",
                "Solving for Ux, Initial residual = 1e-02, Final residual = 1e-04, No Iterations 1",
                "Solving for Ux, Initial residual = 9e-03, Final residual = 1e-04, No Iterations 1",
                "Time = 2",
                "shockPosition = 0.51",
                "Cd = 0.201",
                "time step continuity errors : sum local = 1e-8, global = 9e-6, cumulative = 1e-3",
                "Solving for Ux, Initial residual = 8e-03, Final residual = 1e-04, No Iterations 1",
                "Solving for Ux, Initial residual = 8e-03, Final residual = 1e-04, No Iterations 1",
            ],
        ),
    )

    payload = knife.converge_payload(log, strict=True)

    assert payload["strict"] is True
    assert payload["shock"]["ok"] is True
    assert payload["drag"]["ok"] is True
    assert payload["mass"]["ok"] is True
    assert payload["strict_ok"] is True


def test_watch_external_payload_passes_through_arguments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _make_case(tmp_path / "case")
    seen: dict[str, object] = {}

    class FakeProcess:
        def __init__(self, cmd: list[str], **kwargs: object) -> None:
            self.pid = 4242
            seen["cmd"] = cmd
            seen.update(kwargs)

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(watch_service.subprocess, "Popen", FakeProcess)

    payload = watch.external_watch_payload(
        case,
        command=["python", "watcher.py", "--foo", "bar"],
        dry_run=False,
    )

    assert payload["pid"] == 4242
    assert payload["returncode"] == 0
    assert payload["ok"] is True
    assert seen["cmd"] == ["python", "watcher.py", "--foo", "bar"]
    assert seen["cwd"] == case


def test_watch_start_payload_uses_runner_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.setattr(watch_service.case_source_service, "require_case_dir", lambda _path: case)

    dry = watch_service.start_payload(
        case,
        name="solver",
        command=["simpleFoam"],
        dry_run=True,
        kind="solver",
    )
    assert dry["ok"] is True
    assert dry["kind"] == "solver"

    with pytest.raises(ValueError, match="unsupported job kind"):
        watch_service.start_payload(
            case,
            name="solver",
            command=["simpleFoam"],
            kind="bad",
        )

    with pytest.raises(ValueError, match="command is required"):
        watch_service.start_payload(
            case,
            name="solver",
            command=[],
            dry_run=False,
        )

    monkeypatch.setattr(watch_service, "register_job", lambda *_a, **_k: "job-42")

    def _exec(case_path: Path, name: str, cmd: list[str], **kwargs: object) -> object:
        register_job_fn = cast(
            "Callable[[Path, str, int, str, Path | None], str]",
            kwargs["register_job_fn"],
        )
        log_path = kwargs["log_path"]
        assert isinstance(log_path, Path)
        register_job_fn(case_path, name, 321, " ".join(cmd), log_path)
        return watch_service.runner_service.RunResult(0, "", "", pid=321, log_path=log_path)

    monkeypatch.setattr(watch_service.runner_service, "execute_case_command", _exec)

    payload = watch_service.start_payload(
        case,
        name="watcher",
        command=["python", "watcher.py"],
        detached=False,
        kind="watcher",
        env={"FOO": "BAR"},
    )
    assert payload["ok"] is True
    assert payload["job_id"] == "job-42"
    assert payload["pid"] == 321
    assert payload["kind"] == "watcher"
    assert "FOO" in payload["env_keys"]


def test_run_matrix_axis_parse_and_case_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    axes = run.parse_matrix_axes(
        [
            "application=simpleFoam,pisoFoam",
            "constant/chemistryProperties:modifiedTemperature=on,off",
        ],
        default_dict="system/controlDict",
    )
    assert len(axes) == 2
    assert axes[0]["dict_path"] == "system/controlDict"
    assert axes[1]["entry"] == "modifiedTemperature"

    with pytest.raises(ValueError, match="invalid matrix axis"):
        run.parse_matrix_axes(["broken"], default_dict="system/controlDict")

    monkeypatch.setattr(run, "build_matrix_cases", lambda *_a, **_k: [])
    payload = run.matrix_case_payload(case, axes=axes, dry_run=False)
    assert payload["case_count"] == 4
    assert payload["cases"][0]["case"].startswith(str(case.parent))
    assert (
        "system/controlDict:application" in payload["cases"][0]["values"]
        or "constant/chemistryProperties:modifiedTemperature" in payload["cases"][0]["values"]
    )


def test_run_parametric_helpers_and_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    assert run.parse_sweep_values(["a,b", " c ", ""]) == ["a", "b", "c"]
    grid_axes = run.parse_grid_axes(
        ["application=simpleFoam,pisoFoam"],
        default_dict="system/controlDict",
    )
    assert grid_axes[0]["dict_path"] == "system/controlDict"

    monkeypatch.setattr(run, "build_parametric_cases", lambda *_a, **_k: [case.parent / "single_1"])
    single = run.parametric_case_payload(
        case,
        dict_path="system/controlDict",
        entry="application",
        values=["simpleFoam"],
        csv_path=None,
        grid_axes=[],
        run_solver=False,
    )
    assert single["mode"] == "single"
    assert single["created_count"] == 1

    monkeypatch.setattr(run, "build_parametric_cases_from_csv", lambda *_a, **_k: [case.parent / "csv_1"])
    csv_payload = run.parametric_case_payload(
        case,
        dict_path="system/controlDict",
        entry=None,
        values=[],
        csv_path=Path("study.csv"),
        grid_axes=[],
        run_solver=False,
    )
    assert csv_payload["mode"] == "csv"

    monkeypatch.setattr(run, "build_parametric_cases_from_grid", lambda *_a, **_k: [case.parent / "grid_1"])
    monkeypatch.setattr(
        run,
        "queue_payload",
        lambda **_k: {
            "count": 1,
            "max_parallel": 1,
            "poll_interval": 0.25,
            "dry_run": False,
            "planned": [],
            "started": [],
            "finished": [],
            "failed_to_start": [],
            "ok": True,
        },
    )
    grid_payload = run.parametric_case_payload(
        case,
        dict_path="system/controlDict",
        entry=None,
        values=[],
        csv_path=None,
        grid_axes=[{"dict_path": "system/controlDict", "entry": "application", "values": ["simpleFoam"]}],
        run_solver=True,
    )
    assert grid_payload["mode"] == "grid"
    assert cast("dict[str, object]", grid_payload["queue"])["ok"] is True

    with pytest.raises(ValueError, match="choose only one mode"):
        run.parametric_case_payload(
            case,
            dict_path="system/controlDict",
            entry="application",
            values=["simpleFoam"],
            csv_path=Path("study.csv"),
            grid_axes=[{"dict_path": "system/controlDict", "entry": "application", "values": ["x"]}],
        )


def test_run_queue_payload_dry_run_and_active_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_a = _make_case(tmp_path / "caseA")
    case_b = _make_case(tmp_path / "caseB")
    monkeypatch.setattr(run, "solver_command", lambda _case, **_k: ("simpleFoam", ["simpleFoam"]))
    dry = run.queue_payload(
        cases=[case_a, case_b],
        max_parallel=2,
        dry_run=True,
    )
    assert dry["count"] == 2
    assert dry["planned"][0]["name"] == "simpleFoam"

    pids = iter([101, 202])
    monkeypatch.setattr(
        run,
        "execute_case_command",
        lambda case, _name, _cmd, **_k: run.RunResult(
            0,
            "",
            "",
            pid=next(pids),
            log_path=case / "log.simpleFoam",
        ),
    )
    poll = {"calls": 0}

    def _pid_running(pid: int) -> bool:
        poll["calls"] += 1
        return poll["calls"] <= 2 and pid in {101, 202}

    monkeypatch.setattr(run, "_pid_running", _pid_running)
    monkeypatch.setattr(run.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        run,
        "status_row_payload",
        lambda case, **_k: {
            "case": str(case),
            "state": "done",
            "latest_time": 1.0,
            "eta_seconds": 0.0,
            "stop_reason": "end_time_reached",
        },
    )

    queue = run.queue_payload(
        cases=[case_a, case_b],
        max_parallel=1,
        dry_run=False,
    )
    assert queue["ok"] is True
    assert len(queue["started"]) == 2
    assert len(queue["finished"]) == 2


def test_run_status_set_payload_and_reason_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "set"
    case_a = _make_case(root / "caseA")
    case_b = _make_case(root / "caseB")
    summary = root / "summary.csv"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text("case\ncaseA\n")

    monkeypatch.setattr(
        knife_service,
        "status_payload",
        lambda case, **_k: {
            "case": str(case),
            "running": case.name == "caseB",
            "latest_time": 1.0,
            "eta_seconds_to_end_time": 5.0,
            "solver_error": None,
            "log_fresh": False,
            "jobs_running": 1 if case.name == "caseB" else 0,
            "run_time_control": {
                "failed": 0,
                "end_time": 1.0,
                "criteria": [],
            },
        },
    )
    rows = run.resolve_case_set(
        set_dir=root,
        explicit_cases=[],
        case_glob="case*",
        summary_csv=Path("summary.csv"),
    )
    assert rows == [case_a.resolve()]
    status = run.status_set_payload(
        set_dir=root,
        explicit_cases=[case_a, case_b],
        case_glob="case*",
        summary_csv=None,
        lightweight=True,
    )
    assert status["count"] == 2
    states = {Path(row["case"]).name: row["state"] for row in status["rows"]}
    assert states["caseA"] == "done"
    assert states["caseB"] == "running"


def test_run_matrix_and_catalog_helper_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.setattr(run, "tool_catalog_payload", lambda _case: {"case": str(case), "tools": ["a", "b"]})
    assert run.tool_catalog_names(case) == ["a", "b"]

    out = run.write_tool_catalog_json(case, output_path=Path("meta/catalog.json"))
    assert out == (case / "meta" / "catalog.json").resolve()
    assert out.is_file()

    axes = run.parse_matrix_axes(["   ", "application=simpleFoam"], default_dict="system/controlDict")
    assert len(axes) == 1

    with pytest.raises(ValueError, match="dict path"):
        run.parse_matrix_axes([":entry=v"], default_dict="system/controlDict")
    with pytest.raises(ValueError, match="entry"):
        run.parse_matrix_axes(["system/controlDict:=v"], default_dict="system/controlDict")
    with pytest.raises(ValueError, match="values"):
        run.parse_matrix_axes(["application="], default_dict="system/controlDict")
    with pytest.raises(ValueError, match="at least one --param axis"):
        run.parse_matrix_axes([], default_dict="system/controlDict")

    combo = [
        (cast("run.MatrixAxis", {"dict_path": "system/controlDict", "entry": "application", "values": ["a"]}), "a"),
        (cast("run.MatrixAxis", {"dict_path": "constant/chemistryProperties", "entry": "application", "values": ["b"]}), "b"),
    ]
    name = run.matrix_case_name("base", combo)
    assert "system_controlDict_application-a" in name
    assert "constant_chemistryProperties_application-b" in name


def test_run_queue_and_case_set_error_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    with pytest.raises(ValueError, match="max_parallel must be > 0"):
        run.queue_payload(cases=[case], max_parallel=0)

    monkeypatch.setattr(run, "solver_command", lambda _case, **_k: ("simpleFoam", ["simpleFoam"]))
    monkeypatch.setattr(
        run,
        "execute_case_command",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("start failed")),
    )
    monkeypatch.setattr(run.time, "sleep", lambda _sec: None)
    failed = run.queue_payload(cases=[case], max_parallel=1, dry_run=False)
    assert failed["ok"] is False
    assert failed["failed_to_start"][0]["error"] == "start failed"

    monkeypatch.setattr(
        run,
        "execute_case_command",
        lambda *_a, **_k: run.RunResult(0, "", "", pid=None, log_path=None),
    )
    missing_pid = run.queue_payload(cases=[case], max_parallel=1, dry_run=False)
    assert missing_pid["ok"] is False
    assert "missing background pid" in missing_pid["failed_to_start"][0]["error"]

    root = tmp_path / "set"
    case_a = _make_case(root / "caseA")
    _make_case(root / "caseB")
    resolved = run.resolve_case_set(
        set_dir=root,
        explicit_cases=[],
        case_glob="case*",
        summary_csv=None,
    )
    assert case_a.resolve() in resolved
    assert run._cases_from_summary_csv(root, root / "missing.csv") == []


def test_run_queue_backend_validation_and_foamlib_async_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_a = _make_case(tmp_path / "caseA")
    case_b = _make_case(tmp_path / "caseB")
    with pytest.raises(ValueError, match="backend must be one of"):
        run.queue_payload(cases=[case_a], max_parallel=1, backend="bad")

    monkeypatch.setattr(run, "solver_command", lambda _case, **_k: ("simpleFoam", ["simpleFoam"]))
    seen: dict[str, object] = {}

    def _run_cases_async(case_paths, **kwargs):
        seen["paths"] = list(case_paths)
        seen["kwargs"] = dict(kwargs)
        return [case_b]

    monkeypatch.setattr(run.foamlib_runner, "run_cases_async", _run_cases_async)
    monkeypatch.setattr(
        run,
        "status_row_payload",
        lambda case, **_k: {
            "case": str(case),
            "state": "done",
            "latest_time": 1.0,
            "eta_seconds": 0.0,
            "stop_reason": "end_time_reached",
        },
    )
    payload = run.queue_payload(
        cases=[case_a, case_b],
        max_parallel=2,
        backend="foamlib-async",
        dry_run=False,
    )
    assert payload["backend"] == "foamlib-async"
    assert len(cast("list[object]", payload["started"])) == 2
    assert len(cast("list[object]", payload["finished"])) == 2
    assert payload["ok"] is False
    kwargs = cast("dict[str, object]", seen["kwargs"])
    assert kwargs["slurm"] is False
    assert kwargs["max_parallel"] == 2


def test_run_queue_backend_prepare_parallel_failure_records_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    monkeypatch.setattr(
        run,
        "solver_command",
        lambda _case, **_k: ("simpleFoam-parallel", ["mpirun", "-np", "2", "simpleFoam", "-parallel"]),
    )
    monkeypatch.setattr(
        run,
        "prepare_parallel_case",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad decompose")),
    )
    payload = run.queue_payload(
        cases=[case],
        parallel=2,
        max_parallel=1,
        backend="foamlib-async",
        dry_run=False,
    )
    assert payload["ok"] is False
    assert cast("list[dict[str, str]]", payload["failed_to_start"])[0]["error"] == "bad decompose"


def test_run_state_reason_and_create_case_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert run._sanitize_token("__bad  value__") == "bad_value"
    assert run._case_state({"running": False, "solver_error": "x", "run_time_control": {}}) == "error"
    assert run._case_state({"running": False, "solver_error": None, "run_time_control": {"failed": 1}}) == "failed"
    assert run._case_state({"running": False, "solver_error": None, "run_time_control": {}, "log_fresh": True}) == "recent"
    assert run._case_state({"running": False, "solver_error": None, "run_time_control": {}, "log_fresh": False}) == "stopped"

    assert run._stop_reason({"solver_error": "missing", "run_time_control": {}}, state="error") == "missing"
    assert run._stop_reason(
        {"solver_error": None, "run_time_control": {"criteria": [{"status": "fail", "unmet_reason": "window"}]}},
        state="failed",
    ) == "window"
    assert run._stop_reason(
        {"solver_error": None, "latest_time": 2.0, "run_time_control": {"criteria": [], "end_time": 1.0}},
        state="done",
    ) == "end_time_reached"
    assert run._stop_reason({"solver_error": None, "run_time_control": {"criteria": []}}, state="failed") == "criteria_failed"
    assert run._stop_reason({"solver_error": None, "run_time_control": {"criteria": []}}, state="stopped") == "stopped"

    combo = run._matrix_combo(
        [
            (
                {"dict_path": "system/controlDict", "entry": "application", "values": ["simpleFoam"]},
                "simpleFoam",
            ),
        ],
    )
    assert combo[0][0]["dict_path"] == "system/controlDict"
    assert combo[0][0]["entry"] == "application"
    assert combo[0][1] == "simpleFoam"


def test_run_execute_solver_case_command_foamlib_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    seen: dict[str, object] = {}

    def _run_case(*args: object, **kwargs: object) -> None:
        seen["args"] = args
        seen["kwargs"] = kwargs

    monkeypatch.setattr(run.foamlib_runner, "run_case", _run_case)

    result = run.execute_solver_case_command(
        case,
        "simpleFoam",
        ["simpleFoam"],
        background=False,
    )
    assert result.returncode == 0
    assert result.log_path == case / "log.simpleFoam"
    assert seen["args"] == (case.resolve(), "simpleFoam")
    kwargs = cast("dict[str, object]", seen["kwargs"])
    assert kwargs["parallel"] is False
    assert kwargs["cpus"] is None


def test_run_execute_solver_case_command_fallback_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    seen: dict[str, object] = {}

    def _fallback(*args: object, **kwargs: object) -> run.RunResult:
        seen["args"] = args
        seen["kwargs"] = kwargs
        return run.RunResult(0, "ok\n", "", pid=None, log_path=None)

    monkeypatch.setattr(run, "execute_case_command", _fallback)

    custom_mpi = run.execute_solver_case_command(
        case,
        "simpleFoam-parallel",
        ["mpirun", "-np", "2", "simpleFoam", "-parallel"],
        parallel=2,
        mpi="mpirun",
        background=False,
    )
    assert custom_mpi.returncode == 0
    assert cast("dict[str, object]", seen["kwargs"])["background"] is False

    def _raise_unavailable(*_args: object, **_kwargs: object) -> None:
        raise run.FoamlibUnavailableError()

    monkeypatch.setattr(run.foamlib_runner, "run_case", _raise_unavailable)
    _ = run.execute_solver_case_command(
        case,
        "simpleFoam",
        ["simpleFoam"],
        background=False,
    )
    assert cast("tuple[object, ...]", seen["args"])[0] == case.resolve()


def test_run_execute_solver_case_command_maps_called_process_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")

    def _run_case(*_args: object, **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(7, ["simpleFoam"])

    monkeypatch.setattr(run.foamlib_runner, "run_case", _run_case)
    result = run.execute_solver_case_command(
        case,
        "simpleFoam",
        ["simpleFoam"],
        background=False,
    )
    assert result.returncode == 7
    assert result.log_path == case / "log.simpleFoam"
    assert "See log" in result.stderr

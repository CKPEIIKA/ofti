from __future__ import annotations

import errno
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from ofti.core import run_manifest
from ofti.tools import process_scan_service as scan
from ofti.tools import watch_service


def _make_case(path: Path) -> Path:
    (path / "system").mkdir(parents=True)
    (path / "system" / "controlDict").write_text("application simpleFoam;\n", encoding="utf-8")
    return path


def _write_proc_entry(
    proc_root: Path,
    *,
    pid: int,
    ppid: int,
    cmdline: bytes = b"simpleFoam\x00",
    cwd: Path | None = None,
    stat_text: str | None = None,
) -> Path:
    proc_dir = proc_root / str(pid)
    proc_dir.mkdir()
    if stat_text is None:
        stat_text = f"{pid} (cmd) S {ppid} 0 0\n"
    (proc_dir / "stat").write_text(stat_text, encoding="utf-8")
    (proc_dir / "cmdline").write_bytes(cmdline)
    if cwd is not None:
        (proc_dir / "cwd").symlink_to(cwd, target_is_directory=True)
    return proc_dir


def test_run_manifest_load_verify_and_restore_error_branches(tmp_path: Path) -> None:
    bad_type = tmp_path / "bad-type.json"
    bad_type.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError, match="invalid manifest payload"):
        run_manifest.load_run_manifest(bad_type)

    bad_kind = tmp_path / "bad-kind.json"
    bad_kind.write_text('{"manifest_kind": "other"}', encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported manifest kind"):
        run_manifest.load_run_manifest(bad_kind)

    missing_case = tmp_path / "missing-case.json"
    missing_case.write_text(
        '{"manifest_kind": "ofti_run_manifest", "case": {"path": "missing"}, "inputs": {"files": []}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="case directory not found"):
        run_manifest.verify_run_manifest(missing_case)

    missing_inputs = tmp_path / "missing-inputs.json"
    missing_inputs.write_text(
        (
            '{"manifest_kind": "ofti_run_manifest", "case": {"path": "."}, '
            '"inputs": {"inputs_copy_path": "inputs"}}'
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="recorded inputs directory not found"):
        run_manifest.restore_run_manifest(missing_inputs, tmp_path / "restored")

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    nonempty = tmp_path / "nonempty"
    nonempty.mkdir()
    (nonempty / "x").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="destination already exists and is not empty"):
        run_manifest.restore_run_manifest(missing_inputs, nonempty)


def test_run_manifest_helpers_cover_provenance_and_selection_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    assert run_manifest.collect_case_inputs(case, roots=["system", "missing"])
    assert run_manifest.resolve_manifest_output(case, tmp_path / "explicit.json") == (tmp_path / "explicit.json").resolve()
    assert run_manifest._mesh_hash([{"path": "system/controlDict", "sha256": "x"}]) is None
    assert run_manifest._manifest_roots({"inputs": {"roots": "bad"}}) == run_manifest.DEFAULT_INPUT_ROOTS
    assert run_manifest._normalize_manifest_roots(["system,constant", "system"]) == ["system", "constant"]
    with pytest.raises(ValueError, match="invalid manifest root"):
        run_manifest._normalize_manifest_roots(["bad"])
    assert run_manifest._slug(" a//b  c ") == "a_b_c"

    file_root = case / "singleRoot"
    file_root.write_text("single\n", encoding="utf-8")
    monkeypatch.setattr(run_manifest, "DEFAULT_INPUT_ROOTS", ("missing", "singleRoot"))
    copied = tmp_path / "copied"
    run_manifest._copy_input_roots(case, copied)
    assert (copied / "singleRoot").read_text(encoding="utf-8") == "single\n"

    monkeypatch.setenv("WM_PROJECT_VERSION", "v2312")
    assert run_manifest._selected_env(os.environ)["WM_PROJECT_VERSION"] == "v2312"
    assert run_manifest._parse_env_lines("A=1\nbad\nB=two=2\n") == {"A": "1", "B": "two=2"}


def test_run_manifest_binary_library_and_git_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    solver = tmp_path / "simpleFoam"
    solver.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(run_manifest, "resolve_executable", lambda _name: str(solver))
    assert run_manifest._solver_binary_row("simpleFoam", bashrc=None)["size"] == solver.stat().st_size
    assert run_manifest._solver_binary_row(None, bashrc=None)["name"] is None

    monkeypatch.setattr(run_manifest, "resolve_executable", lambda _name: (_ for _ in ()).throw(FileNotFoundError))
    bashrc = tmp_path / "bashrc"
    bashrc.write_text("# env\n", encoding="utf-8")
    missing_result = SimpleNamespace(returncode=0, stdout=str(tmp_path / "missing"), stderr="")
    monkeypatch.setattr(run_manifest, "run_trusted", lambda *_a, **_k: missing_result)
    assert run_manifest._resolve_solver_binary_path("simpleFoam", bashrc=bashrc) is None

    env_result = SimpleNamespace(returncode=0, stdout="WM_PROJECT_VERSION=v2312\nbad\n", stderr="")
    monkeypatch.setattr(run_manifest, "run_trusted", lambda *_a, **_k: env_result)
    assert run_manifest._effective_openfoam_env(bashrc)["WM_PROJECT_VERSION"] == "v2312"

    fail_result = SimpleNamespace(returncode=1, stdout="", stderr="bad")
    monkeypatch.setattr(run_manifest, "run_trusted", lambda *_a, **_k: fail_result)
    assert run_manifest._linked_library_rows(solver)["files"] == []

    lib = tmp_path / "libA.so"
    lib.write_text("lib\n", encoding="utf-8")
    ldd = SimpleNamespace(
        returncode=0,
        stdout=(
            f"\nlibA.so => {lib} (0x1)\n"
            "libMissing.so => not found\n"
            "linux-vdso.so\n"
            f"{tmp_path / 'missing-lib.so'} (0x2)\n"
            f"{lib} (0x2)\n"
        ),
        stderr="",
    )
    monkeypatch.setattr(run_manifest, "run_trusted", lambda *_a, **_k: ldd)
    rows = run_manifest._linked_library_rows(solver)
    assert rows["count"] == 1
    assert rows["missing"] == ["libMissing.so => not found"]
    assert run_manifest._ldd_resolved_path("libA.so => relative (0x1)") is None

    monkeypatch.setattr(run_manifest, "run_trusted", lambda *_a, **_k: (_ for _ in ()).throw(OSError("git missing")))
    assert run_manifest._git_capture(tmp_path, "status") == {"ok": False, "stdout": "", "stderr": ""}

    dirty = {
        ("rev-parse", "--show-toplevel"): SimpleNamespace(returncode=0, stdout=f"{tmp_path}\n", stderr=""),
        ("rev-parse", "HEAD"): SimpleNamespace(returncode=0, stdout="abc\n", stderr=""),
        ("status", "--porcelain"): SimpleNamespace(returncode=0, stdout="MM system/controlDict\n", stderr=""),
    }

    def _run_git(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        key = tuple(cmd[3:])
        assert len(key) == 2
        return dirty[(key[0], key[1])]

    monkeypatch.setattr(run_manifest, "run_trusted", _run_git)
    info = run_manifest._git_info(tmp_path)
    assert info["git_dirty"] is True
    assert info["git_dirty_files"] == ["system/controlDict"]
    assert run_manifest._iter_files(solver) == [solver]
    assert run_manifest._normalize_manifest_roots(["system,,0"]) == ["system", "0"]


def test_run_manifest_remaining_error_and_copy_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / "manifest.json"
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "system").write_text("flat system input\n", encoding="utf-8")
    manifest.write_text(
        (
            '{"manifest_kind": "ofti_run_manifest", "case": {"path": "."}, '
            '"inputs": {"inputs_copy_path": "inputs"}}'
        ),
        encoding="utf-8",
    )
    restored = run_manifest.restore_run_manifest(manifest, tmp_path / "flat-restored", only=["system"])
    assert Path(restored["destination"], "system").read_text(encoding="utf-8") == "flat system input\n"

    bashrc = tmp_path / "bashrc"
    bashrc.write_text("# env\n", encoding="utf-8")
    monkeypatch.setattr(run_manifest, "run_trusted", lambda *_a, **_k: (_ for _ in ()).throw(OSError("shell missing")))
    monkeypatch.setattr(run_manifest, "resolve_executable", lambda _name: (_ for _ in ()).throw(FileNotFoundError))
    assert run_manifest._effective_openfoam_env(bashrc) == run_manifest._selected_env(os.environ)
    assert run_manifest._resolve_solver_binary_path("simpleFoam", bashrc=bashrc) is None
    assert run_manifest._linked_library_rows(tmp_path / "simpleFoam") == {
        "count": 0,
        "hash": None,
        "files": [],
        "missing": [],
    }

    monkeypatch.setattr(run_manifest, "run_trusted", lambda *_a, **_k: SimpleNamespace(returncode=1, stdout="", stderr=""))
    assert run_manifest._effective_openfoam_env(bashrc) == run_manifest._selected_env(os.environ)
    assert run_manifest._resolve_solver_binary_path("simpleFoam", bashrc=bashrc) is None

    monkeypatch.setattr(run_manifest, "run_trusted", lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="\n", stderr=""))
    assert run_manifest._resolve_solver_binary_path("simpleFoam", bashrc=bashrc) is None


def test_process_scan_warning_and_proc_reader_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    assert scan.proc_access_warning(proc_root) == "procfs appears empty; live process discovery may be incomplete"

    _write_proc_entry(proc_root, pid=2, ppid=0, cmdline=b"", cwd=None)
    assert "missing pid 1" in str(scan.proc_access_warning(proc_root))

    pid1 = _write_proc_entry(proc_root, pid=1, ppid=0, cmdline=b"", cwd=None)
    assert "unreadable" in str(scan.proc_access_warning(proc_root))
    (pid1 / "comm").write_text("firejail\n", encoding="utf-8")
    assert "sandboxed" in str(scan.proc_access_warning(proc_root))

    bad_root = tmp_path / "bad-proc"
    bad_root.write_text("not a dir", encoding="utf-8")
    assert "procfs unavailable" in str(scan.proc_access_warning(bad_root))
    assert scan.proc_table(bad_root) == {}

    bad_proc = tmp_path / "proc-read"
    bad_proc.mkdir()
    proc = _write_proc_entry(bad_proc, pid=10, ppid=1, cmdline=b"\x00", cwd=None, stat_text="bad")
    assert scan.read_proc_args(proc) == []
    assert scan.read_proc_ppid(proc) == -1
    (proc / "stat").write_text("10 (cmd) S x\n", encoding="utf-8")
    assert scan.read_proc_ppid(proc) == -1

    original_read_text = Path.read_text

    def _raise_for_comm(
        self: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        if self.name == "comm":
            raise OSError("no comm")
        return original_read_text(self, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", _raise_for_comm)
    assert scan.read_proc_comm(proc) is None


def test_process_scan_scope_role_cache_and_case_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan._DISCOVERY_CACHE.clear()
    case = _make_case(tmp_path / "case")
    other = _make_case(tmp_path / "other")
    table = {
        1: scan.ProcEntry(pid=1, ppid=0, args=["mpirun", "-case", str(case), "simpleFoam"], cwd=None),
        2: scan.ProcEntry(pid=2, ppid=1, args=["simpleFoam", "-parallel"], cwd=None),
        3: scan.ProcEntry(pid=3, ppid=0, args=["mpirun"], cwd=other),
        4: scan.ProcEntry(pid=4, ppid=4, args=["simpleFoam"], cwd=None),
    }
    assert scan.launcher_pids_for_case(table, None, case) == {1}
    assert scan.solver_descendant_pids(1, table, None) == [2]
    assert scan.has_ancestor(4, {1}, table) is False
    assert scan.process_role([], None) is None
    assert scan.process_role(["bash", "-lc", "simpleFoam -parallel"], "simpleFoam") == "launcher"
    assert scan._shell_command_has_any_solver(["bash", "-c", "simpleFoam -parallel"]) is True
    assert scan.entry_targets_case(scan.ProcEntry(5, 0, ["simpleFoam", "-case"], None), case) is False
    assert scan.case_candidate_from_args(["simpleFoam", "-case", "sub"], tmp_path) == (tmp_path / "sub").resolve()
    assert scan.case_candidate_from_shell_args([], tmp_path) is None
    assert scan._shell_cd_candidate("cd 'unterminated", tmp_path) == (tmp_path / "'unterminated").resolve()
    assert scan._shell_cd_candidate("cd -; cd rel", tmp_path) == (tmp_path / "rel").resolve()
    assert scan.as_case_dir(case / "system", checked={case / "system"}) == case
    assert scan.launcher_descendant_targets_case(1, table, case) is False
    table[2] = scan.ProcEntry(pid=2, ppid=1, args=["simpleFoam", "-case", str(case)], cwd=None)
    assert scan.launcher_descendant_targets_case(1, table, case) is True
    assert scan.discovery_error_text("operation not permitted") == "case_not_found"
    assert scan.launcher_pid_for_entry(scan.ProcEntry(6, 1, ["simpleFoam"], None), table) == 1
    assert scan._command_head(["a", "b", "c", "d", "e"]) == "a b c d"
    assert scan._command_head([]) == ""
    assert scan._case_to_text(None) == ""
    assert scan._in_scope_case(case, tmp_path, case_root_is_case=False) is True

    entry = scan.ProcEntry(pid=20, ppid=1, args=["simpleFoam"], cwd=case)
    scan._cache_discovery(entry, case, "procfs", proc_root=tmp_path)
    assert scan._cache_lookup(entry, proc_root=tmp_path) is not None
    assert scan._cache_lookup(scan.ProcEntry(pid=20, ppid=2, args=["simpleFoam"], cwd=case), proc_root=tmp_path) is None
    old = scan.ProcessCaseCacheEntry(30, 1, "simpleFoam", case, "procfs", time.time() - 9999, tmp_path.resolve())
    scan._DISCOVERY_CACHE[30] = old
    scan._cleanup_discovery_cache()
    assert 30 not in scan._DISCOVERY_CACHE

    original_is_file = Path.is_file

    def _raise_is_file(self: Path) -> bool:
        if self.name == "controlDict":
            raise OSError("blocked")
        return original_is_file(self)

    monkeypatch.setattr(Path, "is_file", _raise_is_file)
    assert scan.is_case_dir(case) is False


def test_process_scan_remaining_branch_helpers(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "case")
    other = _make_case(tmp_path / "other")
    table = {
        10: scan.ProcEntry(pid=10, ppid=0, args=["mpirun"], cwd=other),
        11: scan.ProcEntry(pid=11, ppid=10, args=["notSolver"], cwd=other),
        20: scan.ProcEntry(pid=20, ppid=0, args=["bash", "-lc", "simpleFoam -parallel"], cwd=case),
        21: scan.ProcEntry(pid=21, ppid=20, args=["simpleFoam"], cwd=None),
        30: scan.ProcEntry(pid=30, ppid=0, args=["simpleFoam", "-case"], cwd=None),
    }
    assert scan.launcher_pids_for_case(table, "simplefoam", case) == set()
    assert scan.launcher_has_solver_descendant(10, table, "simplefoam") is False
    assert scan.solver_descendant_pids(10, table, "simplefoam") == []
    assert scan._shell_command_matches_solver([], "simplefoam") is False
    assert scan._shell_command_matches_solver(["python", "-c", "simpleFoam"], "simplefoam") is False
    assert scan._shell_command_matches_solver(["bash", "-c", ""], "simplefoam") is False
    assert scan._shell_command_has_any_solver([]) is False
    assert scan._shell_command_has_any_solver(["python", "-c", "simpleFoam"]) is False
    assert scan._shell_command_has_any_solver(["bash", "-c", "echo ok"]) is False
    assert scan.discovery_error_text("custom error") == "custom error"
    assert scan.infer_case_path(scan.ProcEntry(pid=40, ppid=40, args=["simpleFoam"], cwd=None), table) is None
    assert scan.case_candidate_from_args(["simpleFoam", "-case"], case) is None
    candidate = scan.case_candidate_from_args(["simpleFoam", "-case", "rel"], None)
    assert candidate is not None and candidate.is_absolute()
    assert scan.case_candidate_from_shell_args(["bash", "-lc", ""], case) is None
    shell_candidate = scan._shell_cd_candidate("; ; cd rel", None)
    assert shell_candidate is not None and shell_candidate.is_absolute()
    assert scan.guess_solver_from_args(["python"]) == "unknown"
    assert scan.launcher_pid_for_entry(scan.ProcEntry(pid=21, ppid=20, args=["simpleFoam"], cwd=None), table) == 20

    scan._DISCOVERY_CACHE.clear()
    launcher_cases = {10: other}
    discovery = scan.discover_case(
        scan.ProcEntry(pid=11, ppid=10, args=["notSolver"], cwd=None),
        table,
        launcher_cases=launcher_cases,
        proc_root=tmp_path,
    )
    assert discovery.source == "launcher"
    assert discovery.case == other

    entry = scan.ProcEntry(pid=50, ppid=1, args=["simpleFoam"], cwd=case)
    scan._cache_discovery(entry, case, "procfs", proc_root=tmp_path)
    assert scan._cache_lookup(entry, proc_root=tmp_path / "other-root") is None
    assert scan._cache_lookup(scan.ProcEntry(pid=50, ppid=1, args=["other"], cwd=case), proc_root=tmp_path) is None
    scan._DISCOVERY_CACHE[50] = scan.ProcessCaseCacheEntry(
        50,
        1,
        "simpleFoam",
        case,
        "procfs",
        time.time() - 9999,
        tmp_path.resolve(),
    )
    assert scan._cache_lookup(entry, proc_root=tmp_path) is None


def test_process_scan_scan_and_discovery_edge_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    other = _make_case(tmp_path / "other")
    proc_root = tmp_path / "proc-edge"
    proc_root.mkdir()
    _write_proc_entry(proc_root, pid=1, ppid=0, cmdline=b"firejail\x00", cwd=None)
    assert "sandboxed" in str(scan.proc_access_warning(proc_root))

    proc_dir = proc_root / "2"
    proc_dir.mkdir()
    (proc_dir / "comm").write_text("\n", encoding="utf-8")
    assert scan.read_proc_comm(proc_dir) is None

    out_of_scope = {
        1: scan.ProcEntry(pid=1, ppid=0, args=["simpleFoam"], cwd=other),
        2: scan.ProcEntry(pid=2, ppid=0, args=["mpirun"], cwd=case),
    }
    monkeypatch.setattr(scan, "proc_table", lambda _root: out_of_scope)
    assert scan.scan_proc_solver_processes(case, "simpleFoam", tracked_pids=set(), proc_root=proc_root) == []

    launcher_only = {
        3: scan.ProcEntry(pid=3, ppid=0, args=["mpirun"], cwd=case),
        4: scan.ProcEntry(pid=4, ppid=3, args=["python"], cwd=case),
    }
    monkeypatch.setattr(scan, "proc_table", lambda _root: launcher_only)
    assert scan.scan_proc_solver_processes(case, None, tracked_pids=set(), proc_root=proc_root) == []

    launcher_cases = {10: case}
    no_inferred_case = {
        10: scan.ProcEntry(pid=10, ppid=0, args=["mpirun"], cwd=None),
        11: scan.ProcEntry(pid=11, ppid=10, args=["simpleFoam"], cwd=None),
    }
    discovery = scan.discover_case(
        no_inferred_case[11],
        no_inferred_case,
        launcher_cases=launcher_cases,
        proc_root=proc_root,
    )
    assert discovery.case == case
    assert discovery.source == "launcher"

    original_resolve = Path.resolve

    def _raise_for_cwd(self: Path, strict: bool = False) -> Path:
        if self.name == "cwd":
            raise OSError(errno.EACCES, "permission denied")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _raise_for_cwd)
    assert scan.proc_cwd_with_error(proc_dir) == (None, "permission denied")


def test_watch_service_tracked_process_timeout_and_signal_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path / "case")
    real_pid_running = watch_service._pid_running
    monkeypatch.setattr(watch_service, "_pid_running", lambda _pid: True)
    proc = watch_service.tracked_job_process(case, pid=44, job_id=None)
    assert proc.poll() is None
    with pytest.raises(subprocess.TimeoutExpired):
        proc.wait(timeout=0.01)

    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(watch_service.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    proc.terminate()
    assert sent == [(44, watch_service.signal.SIGTERM)]

    monkeypatch.setattr(watch_service, "_pid_running", real_pid_running)
    monkeypatch.setattr(watch_service.os, "kill", lambda _pid, _sig: (_ for _ in ()).throw(OSError("gone")))
    assert watch_service._pid_running(44) is False
    monkeypatch.setattr(watch_service.os, "kill", lambda _pid, _sig: None)
    assert watch_service._pid_running(44) is True
    assert watch_service._pid_running(0) is False


def test_run_manifest_loads_legacy_receipt_kind(tmp_path: Path) -> None:
    legacy = tmp_path / "receipt.json"
    legacy.write_text('{"receipt_kind": "ofti_run_receipt"}', encoding="utf-8")

    assert run_manifest.load_run_manifest(legacy)["receipt_kind"] == "ofti_run_receipt"

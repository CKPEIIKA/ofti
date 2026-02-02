from __future__ import annotations

from pathlib import Path

from ofti.tools.solver import run_current_solver_parallel


class FakeScreen:
    def __init__(self) -> None:
        self._keys: list[int] = []

    def clear(self) -> None:
        pass

    def addstr(self, *_args, **_kwargs) -> None:
        pass

    def refresh(self) -> None:
        pass

    def getch(self) -> int:
        if self._keys:
            return self._keys.pop(0)
        return ord("h")


def _write_control_dict(case_dir: Path) -> None:
    control = case_dir / "system" / "controlDict"
    control.parent.mkdir(parents=True, exist_ok=True)
    control.write_text("application simpleFoam;\n")


def _write_decompose_dict(case_dir: Path) -> None:
    decompose = case_dir / "system" / "decomposeParDict"
    decompose.parent.mkdir(parents=True, exist_ok=True)
    decompose.write_text("numberOfSubdomains 4;\n")


def _write_zero_fields(case_dir: Path) -> None:
    zero_dir = case_dir / "0"
    zero_dir.mkdir()
    (zero_dir / "U").write_text("internalField uniform (0 0 0);\n")
    (zero_dir / "p").write_text("internalField uniform 0;\n")


def test_run_current_solver_parallel_invokes_mpirun(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    _write_control_dict(case_dir)
    _write_decompose_dict(case_dir)
    _write_zero_fields(case_dir)

    seen: dict[str, list[str]] = {}

    def fake_run(_stdscr, _case, _solver, cmd):
        seen["cmd"] = list(cmd)

    monkeypatch.setattr("ofti.tools.solver.read_entry", lambda *_a, **_k: "simpleFoam;")
    monkeypatch.setattr("ofti.tools.solver.read_number_of_subdomains", lambda *_a, **_k: 4)
    monkeypatch.setattr("ofti.tools.solver.resolve_executable", lambda *_a: "mpirun")
    monkeypatch.setattr("ofti.tools.solver._run_solver_live_cmd", fake_run)

    run_current_solver_parallel(FakeScreen(), case_dir)

    assert seen["cmd"] == ["mpirun", "-np", "4", "simpleFoam", "-parallel"]

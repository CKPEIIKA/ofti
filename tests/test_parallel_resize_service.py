from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ofti.core.case import read_number_of_subdomains
from ofti.tools import parallel_resize_service


def _case(tmp_path: Path) -> Path:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "constant" / "polyMesh").mkdir(parents=True)
    (case / "0").mkdir()
    (case / "10").mkdir()
    (case / "0" / "U").write_text("internalField uniform (0 0 0);\n")
    (case / "0" / "p").write_text("internalField uniform 0;\n")
    (case / "system" / "controlDict").write_text(
        "\n".join(
            [
                "FoamFile",
                "{",
                "    version 2.0;",
                "    format ascii;",
                "    class dictionary;",
                "    object controlDict;",
                "}",
                "application simpleFoam;",
                "startFrom startTime;",
                "startTime 0;",
                "stopAt endTime;",
                "endTime 100;",
                "",
            ],
        ),
    )
    (case / "system" / "decomposeParDict").write_text(
        "\n".join(
            [
                "FoamFile",
                "{",
                "    version 2.0;",
                "    format ascii;",
                "    class dictionary;",
                "    object decomposeParDict;",
                "}",
                "numberOfSubdomains 2;",
                "method scotch;",
                "",
            ],
        ),
    )
    (case / "processor0").mkdir()
    (case / "processor1").mkdir()
    return case


def test_parallel_resize_dry_run_plans_safe_steps(tmp_path: Path) -> None:
    payload = parallel_resize_service.parallel_resize_payload(
        _case(tmp_path),
        from_ranks=2,
        to_ranks=4,
        dry_run=True,
    )

    assert payload["ok"] is True
    assert payload["from"] == 2
    assert payload["to"] == 4
    assert [row["step"] for row in payload["steps"]] == [
        "snapshot",
        "write-now",
        "reconstruct",
        "clean-processors",
        "set-subdomains",
        "resume-from-latest",
        "decompose",
        "start",
    ]
    assert "no files changed" in str(payload["rollback"])


def test_parallel_resize_executes_reconstruct_decompose_and_restart(
    tmp_path: Path,
    monkeypatch,
) -> None:
    case = _case(tmp_path)
    commands: list[list[str]] = []

    monkeypatch.setattr(
        parallel_resize_service.knife_service,
        "current_payload",
        lambda *_a, **_k: {"jobs_running": 0},
    )

    def _execute_case_command(_case, _name, command, **_kwargs):
        commands.append(list(command))
        return SimpleNamespace(returncode=0, stdout="", stderr="", log_path=None)

    monkeypatch.setattr(
        parallel_resize_service.run_ops,
        "execute_case_command",
        _execute_case_command,
    )
    monkeypatch.setattr(
        parallel_resize_service.run_ops,
        "solver_command",
        lambda _case, **_kwargs: (
            "simpleFoam-parallel",
            ["mpirun", "-np", "4", "simpleFoam", "-parallel"],
        ),
    )
    monkeypatch.setattr(
        parallel_resize_service.run_ops,
        "execute_solver_case_command",
        lambda *_a, **_k: SimpleNamespace(pid=123, log_path=case / "log.simpleFoam"),
    )

    payload = parallel_resize_service.parallel_resize_payload(case, from_ranks=2, to_ranks=4)

    assert payload["ok"] is True
    assert payload["pid"] == 123
    assert payload["input_snapshot_path"]
    snapshot = Path(str(payload["input_snapshot_path"]))
    assert (snapshot / "inputs" / "system" / "controlDict").is_file()
    assert (snapshot / "inputs" / "constant").is_dir()
    assert commands == [
        ["reconstructPar", "-latestTime"],
        ["decomposePar", "-force", "-latestTime"],
    ]
    assert not (case / "processor0").exists()
    assert read_number_of_subdomains(case / "system" / "decomposeParDict") == 4
    control = (case / "system" / "controlDict").read_text()
    assert "startFrom latestTime;" in control
    assert "stopAt endTime;" in control
    write_step = next(row for row in payload["steps"] if row["step"] == "write-now")
    assert write_step["acknowledged"] is True
    assert "To rollback inputs" in str(payload["rollback"])


def test_parallel_resize_stop_timeout_reports_rollback(tmp_path: Path, monkeypatch) -> None:
    case = _case(tmp_path)
    monkeypatch.setattr(
        parallel_resize_service.knife_service,
        "current_payload",
        lambda *_a, **_k: {"jobs_running": 1},
    )

    payload = parallel_resize_service.parallel_resize_payload(
        case,
        from_ranks=2,
        to_ranks=4,
        stop_timeout=0.0,
    )

    assert payload["ok"] is False
    assert "writeNow" in payload["error"]
    assert payload["input_snapshot_path"]
    assert "To rollback inputs" in payload["rollback"]


def test_parallel_resize_requires_decomposed_case_for_execution(tmp_path: Path, monkeypatch) -> None:
    case = _case(tmp_path)
    for path in (case / "processor0", case / "processor1"):
        path.rmdir()
    monkeypatch.setattr(
        parallel_resize_service.knife_service,
        "current_payload",
        lambda *_a, **_k: {"jobs_running": 0},
    )

    payload = parallel_resize_service.parallel_resize_payload(
        case,
        from_ranks=2,
        to_ranks=4,
    )

    assert payload["ok"] is False
    assert payload["decomposed"] is False
    assert "processor* directories" in str(payload["error"])

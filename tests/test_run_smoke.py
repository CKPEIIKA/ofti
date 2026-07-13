from __future__ import annotations

import json
import os
from pathlib import Path

from ofti.app import cli_tools
from ofti.tools.cli_tools import run, run_smoke


def _write_field(path: Path, *, vector: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    value = "uniform (0 0 0)" if vector else "uniform 1"
    cls = "volVectorField" if vector else "volScalarField"
    path.write_text(
        f"FoamFile{{ version 2.0; format ascii; class {cls}; }}\ninternalField {value};\nboundaryField{{}}\n",
        encoding="utf-8",
    )


def _make_case(path: Path) -> Path:
    (path / "system").mkdir(parents=True)
    (path / "0").mkdir()
    (path / "system" / "controlDict").write_text(
        "FoamFile\n"
        "{\n"
        "    version 2.0;\n"
        "    format ascii;\n"
        "    class dictionary;\n"
        "    object controlDict;\n"
        "}\n"
        "application fakeFoam;\n"
        "startFrom latestTime;\n"
        "deltaT 2;\n"
        "endTime 100;\n"
        "writeInterval 50;\n",
        encoding="utf-8",
    )
    _write_field(path / "0" / "U", vector=True)
    _write_field(path / "0" / "p")
    return path


def _install_fake_solver(bin_dir: Path) -> None:
    bin_dir.mkdir()
    solver = bin_dir / "fakeFoam"
    solver.write_text(
        "#!/bin/sh\n"
        "echo 'Time = 2'\n"
        "echo 'Solving for p, Initial residual = 1e-3, Final residual = 1e-6'\n"
        "mkdir -p 2\n"
        "cp 0/p 2/p\n"
        "cp 0/U 2/U\n"
        "echo 'End'\n",
        encoding="utf-8",
    )
    solver.chmod(0o755)


def test_smoke_payload_runs_real_solver_script_on_copied_case(
    tmp_path: Path,
    monkeypatch,
) -> None:
    case = _make_case(tmp_path / "case")
    _install_fake_solver(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")

    payload = run.smoke_payload(
        case,
        iterations=1,
        timeout=5,
        output_root=tmp_path / "smoke",
        run_physical=True,
        physical_fields=["p"],
    )

    assert payload["ok"] is True
    assert payload["copied"] is True
    assert payload["times_seen"] == [2.0]
    assert payload["iterations_completed"] == 1
    assert payload["iteration_count_exact"] is True
    assert payload["checkpoint_ok"] is True
    smoke_case = Path(str(payload["case"]))
    assert smoke_case != case.resolve()
    assert (smoke_case / "2" / "p").is_file()
    control_text = (smoke_case / "system" / "controlDict").read_text()
    assert any(f"adjustTimeStep {value};" in control_text for value in ("false", "no"))
    assert (tmp_path / "smoke" / "summary.json").is_file()
    assert "physical" in payload


def test_run_smoke_cli_json_uses_real_subprocess(tmp_path: Path, monkeypatch, capsys) -> None:
    case = _make_case(tmp_path / "case")
    _install_fake_solver(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")

    code = cli_tools.main(
        [
            "run",
            "smoke",
            str(case),
            "--iterations",
            "1",
            "--timeout",
            "5s",
            "--out",
            str(tmp_path / "cli-smoke"),
            "--json",
        ],
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] is True
    assert payload["returncode"] == 0
    assert Path(payload["log_path"]).read_text(encoding="utf-8").count("Time =") == 1


def test_smoke_requires_exact_iterations_and_written_checkpoint(tmp_path: Path, monkeypatch) -> None:
    case = _make_case(tmp_path / "case")
    (case / "system" / "controlDict").write_text(
        (case / "system" / "controlDict").read_text() + "adjustTimeStep yes;\n",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    solver = bin_dir / "fakeFoam"
    solver.write_text(
        "#!/bin/sh\n"
        'for time in 2 4 6 8 10; do echo "Time = $time"; done\n'
        "mkdir -p 10\n"
        "cp 0/p 10/p\n"
        "cp 0/U 10/U\n"
        "echo End\n",
        encoding="utf-8",
    )
    solver.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

    payload = run.smoke_payload(case, iterations=5, timeout=5, output_root=tmp_path / "smoke")

    assert payload["ok"] is True
    assert payload["iterations_completed"] == 5
    assert payload["requested_iterations_reached"] is True
    assert payload["target_time_reached"] is True
    assert payload["latest_written_time"] == "10"
    assert payload["failure_reason"] is None


def test_smoke_rejects_zero_exit_without_requested_iterations_or_checkpoint(tmp_path: Path, monkeypatch) -> None:
    case = _make_case(tmp_path / "case")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    solver = bin_dir / "fakeFoam"
    solver.write_text("#!/bin/sh\necho 'Time = 2'\necho End\n", encoding="utf-8")
    solver.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

    payload = run.smoke_payload(case, iterations=5, timeout=5, output_root=tmp_path / "smoke")

    assert payload["returncode"] == 0
    assert payload["end_seen"] is True
    assert payload["ok"] is False
    assert payload["iterations_completed"] == 1
    assert payload["checkpoint_ok"] is False
    assert payload["failure_reason"] == "requested_iterations_or_common_checkpoint_not_reached"


def test_run_smoke_cli_returns_failure_for_incomplete_contract(tmp_path: Path, monkeypatch, capsys) -> None:
    case = _make_case(tmp_path / "case")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    solver = bin_dir / "fakeFoam"
    solver.write_text("#!/bin/sh\necho 'Time = 2'\necho End\n", encoding="utf-8")
    solver.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

    code = cli_tools.main(
        [
            "run",
            "smoke",
            str(case),
            "--iterations",
            "5",
            "--out",
            str(tmp_path / "cli-incomplete"),
            "--json",
        ],
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["ok"] is False
    assert payload["requested_iterations_reached"] is False
    assert payload["checkpoint_required"] is True


def test_parallel_smoke_rejects_checkpoint_missing_on_one_rank(tmp_path: Path) -> None:
    case = tmp_path / "case"
    for processor in ("processor0", "processor1"):
        _write_field(case / processor / "0" / "p")
    _write_field(case / "processor0" / "10" / "p")
    log_text = "\n".join([*(f"Time = {time}" for time in (2, 4, 6, 8, 10)), "End"])

    incomplete = run_smoke._smoke_verification(
        case,
        log_text,
        iterations=5,
        delta_t=2,
        parallel=2,
        returncode=0,
        timed_out=False,
    )
    _write_field(case / "processor1" / "10" / "p")
    complete = run_smoke._smoke_verification(
        case,
        log_text,
        iterations=5,
        delta_t=2,
        parallel=2,
        returncode=0,
        timed_out=False,
    )

    assert incomplete["ok"] is False
    assert incomplete["checkpoint_ok"] is False
    assert incomplete["checkpoint"]["missing_latest_processors"] == ["processor1"]
    assert complete["ok"] is True
    assert complete["checkpoint_ok"] is True
    assert complete["latest_complete_processor_time"] == "10"

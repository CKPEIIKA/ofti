from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast

import pytest

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
        options=run.SmokeOptions(
            iterations=1,
            timeout=5,
            output_root=tmp_path / "smoke",
            run_physical=True,
            physical_fields=["p"],
        ),
    )

    assert payload["ok"] is True
    assert payload["copied"] is True
    assert payload["times_seen"] == [2.0]
    assert payload["iterations_completed"] == 1
    assert payload["iteration_count_exact"] is True
    assert payload["checkpoint_ok"] is True
    assert payload["clean_exit"] is True
    assert payload["output_readable"] is True
    assert {row["field"] for row in payload["readable_fields"]} == {"U", "p"}
    smoke_case = Path(str(payload["case"]))
    assert smoke_case != case.resolve()
    assert (smoke_case / "2" / "p").is_file()
    control_text = (smoke_case / "system" / "controlDict").read_text()
    assert any(f"adjustTimeStep {value};" in control_text for value in ("false", "no"))
    assert (tmp_path / "smoke" / "summary.json").is_file()
    assert "physical" in payload


def test_smoke_validates_bounds_and_existing_output(tmp_path: Path) -> None:
    case = _make_case(tmp_path / "case")

    with pytest.raises(ValueError, match="iterations must be > 0"):
        run.smoke_payload(case, options=run.SmokeOptions(iterations=0))
    with pytest.raises(ValueError, match="timeout must be > 0"):
        run.smoke_payload(case, options=run.SmokeOptions(timeout=0))

    output_root = tmp_path / "smoke"
    (output_root / "case").mkdir(parents=True)
    with pytest.raises(ValueError, match="smoke output case already exists"):
        run.smoke_payload(case, options=run.SmokeOptions(output_root=output_root))


def test_smoke_in_place_reports_source_case_without_copying(tmp_path: Path, monkeypatch) -> None:
    case = _make_case(tmp_path / "case")
    _install_fake_solver(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")

    payload = run.smoke_payload(
        case,
        options=run.SmokeOptions(
            iterations=1,
            timeout=5,
            output_root=tmp_path / "smoke",
            in_place=True,
        ),
    )

    assert payload["ok"] is True
    assert payload["copied"] is False
    assert Path(str(payload["case"])) == case.resolve()
    assert (case / "2" / "p").is_file()


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


def test_smoke_command_maps_timeout_to_bounded_result(tmp_path: Path, monkeypatch) -> None:
    def timed_run(*_args: object, **_kwargs: object) -> object:
        raise run_smoke.subprocess.TimeoutExpired(
            ["fakeFoam"],
            timeout=0.1,
            output=b"partial stdout\n",
            stderr=b"partial stderr\n",
        )

    monkeypatch.setattr(run_smoke.subprocess, "run", timed_run)

    result, timed_out = run_smoke._run_smoke_command(
        tmp_path,
        ["fakeFoam"],
        timeout=0.1,
        log_path=tmp_path / "log.fakeFoam",
    )

    assert timed_out is True
    assert result.returncode == 124
    assert result.stdout == "partial stdout\n"
    assert result.stderr == "partial stderr\n"
    assert (tmp_path / "log.fakeFoam").read_text(encoding="utf-8") == ("partial stdout\npartial stderr\n")


def test_run_smoke_cli_forwards_reconstruction_request(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    case = _make_case(tmp_path / "case")
    captured: dict[str, object] = {}

    def smoke_payload(case_dir: Path, **kwargs: object) -> dict[str, object]:
        options = cast("run_smoke.SmokeOptions", kwargs["options"])
        captured["reconstruct"] = options.reconstruct
        return {"case": str(case_dir), "ok": True}

    monkeypatch.setattr(run, "smoke_payload", smoke_payload)

    code = cli_tools.main(["run", "smoke", str(case), "--reconstruct", "--json"])

    assert code == 0
    assert captured["reconstruct"] is True
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_smoke_normalization_preserves_unrelated_numeric_text(tmp_path: Path, monkeypatch) -> None:
    case = _make_case(tmp_path / "case")
    control = case / "system" / "controlDict"
    original = control.read_text(encoding="utf-8")
    control.write_text(
        original
        + "rhoInf 0.00666666667;\n"
        + "Aref 0.000706858347;\n"
        + "functions\n{\n    probe { point (-0.0152362205 0 0); }\n}\n",
        encoding="utf-8",
    )
    source_before = control.read_bytes()
    _install_fake_solver(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")

    payload = run.smoke_payload(
        case,
        options=run.SmokeOptions(
            iterations=1,
            timeout=5,
            output_root=tmp_path / "smoke",
            core_only=True,
        ),
    )

    normalized = payload["normalized_control"]
    smoke_text = Path(str(normalized["controlDict"])).read_text(encoding="utf-8")
    assert payload["ok"] is True
    assert normalized["text_preserving"] is True
    assert "controlDict.before" in normalized["diff"]
    assert "rhoInf 0.00666666667;" in smoke_text
    assert "Aref 0.000706858347;" in smoke_text
    assert "functions\n{\n}" in smoke_text
    assert "-0.0152362205" not in smoke_text
    assert control.read_bytes() == source_before


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

    payload = run.smoke_payload(
        case,
        options=run.SmokeOptions(iterations=5, timeout=5, output_root=tmp_path / "smoke"),
    )

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

    payload = run.smoke_payload(
        case,
        options=run.SmokeOptions(iterations=5, timeout=5, output_root=tmp_path / "smoke"),
    )

    assert payload["returncode"] == 0
    assert payload["end_seen"] is True
    assert payload["ok"] is False
    assert payload["iterations_completed"] == 1
    assert payload["checkpoint_ok"] is False
    assert payload["failure_reason"] == "requested_iterations_or_common_checkpoint_not_reached"


def test_smoke_clean_exit_requires_exact_end_marker(tmp_path: Path) -> None:
    case = tmp_path / "case"
    _write_field(case / "2" / "p")

    payload = run_smoke._smoke_verification(
        case,
        "Time = 2\nReached endTime without marker\n",
        iterations=1,
        delta_t=2,
        parallel=0,
        returncode=0,
        timed_out=False,
    )

    assert payload["end_seen"] is False
    assert payload["clean_exit"] is False
    assert "solver_end_not_seen" in payload["failure_reasons"]


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
    assert complete["output_readable"] is True


def test_parallel_smoke_reconstruction_verifies_reconstructed_fields(
    tmp_path: Path,
    monkeypatch,
) -> None:
    case = tmp_path / "case"
    for processor in ("processor0", "processor1"):
        _write_field(case / processor / "10" / "p")

    def reconstruct(
        case_path: Path,
        _display: str,
        command: list[str],
        *,
        background: bool,
    ) -> run.RunResult:
        assert command == ["reconstructPar", "-time", "10"]
        assert background is False
        _write_field(case_path / "10" / "p")
        return run.RunResult(0, "reconstructed\n", "")

    monkeypatch.setattr(run, "execute_case_command", reconstruct)

    payload = run_smoke._smoke_reconstruction(
        case,
        "Time = 10\nEnd\n",
        parallel=2,
        requested=True,
    )

    assert payload["ok"] is True
    assert payload["time"] == "10"
    assert payload["returncode"] == 0
    assert payload["output"]["output_readable"] is True


def test_parallel_smoke_reconstruction_reports_solver_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    case = tmp_path / "case"
    for processor in ("processor0", "processor1"):
        _write_field(case / processor / "10" / "p")

    def reconstruct(
        _case_path: Path,
        _display: str,
        command: list[str],
        *,
        background: bool,
    ) -> run.RunResult:
        assert command == ["reconstructPar", "-time", "10"]
        assert background is False
        return run.RunResult(7, "", "reconstruct failed")

    monkeypatch.setattr(run, "execute_case_command", reconstruct)

    payload = run_smoke._smoke_reconstruction(
        case,
        "Time = 10\nEnd\n",
        parallel=2,
        requested=True,
    )

    assert payload["ok"] is False
    assert payload["time"] == "10"
    assert payload["returncode"] == 7
    assert payload["error"] == "reconstruct failed"


def test_smoke_output_readability_reports_malformed_field(tmp_path: Path) -> None:
    case = tmp_path / "case"
    _write_field(case / "2" / "p")
    (case / "2" / "broken").write_text(
        "FoamFile{ class volScalarField; }\ninternalField uniform nope;\n",
        encoding="utf-8",
    )

    payload = run_smoke._smoke_output_readability(case, time_name="2", parallel=0)

    assert payload["output_readable"] is False
    assert payload["readable_fields"] == [
        {
            "field": "p",
            "kind": "scalar",
            "count": 1,
            "components": 1,
        }
    ]
    assert payload["output_read_errors"] == ["broken: internalField has no numeric values: broken"]

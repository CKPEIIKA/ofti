from __future__ import annotations

import json
import os
from pathlib import Path

from ofti.app import cli_tools
from ofti.tools.cli_tools import run


def _write_field(path: Path, *, vector: bool = False) -> None:
    value = "uniform (0 0 0)" if vector else "uniform 1"
    cls = "volVectorField" if vector else "volScalarField"
    path.write_text(
        f"FoamFile{{ version 2.0; format ascii; class {cls}; }}\n"
        f"internalField {value};\n"
        "boundaryField{}\n",
        encoding="utf-8",
    )


def _make_case(path: Path) -> Path:
    (path / "system").mkdir(parents=True)
    (path / "0").mkdir()
    (path / "system" / "controlDict").write_text(
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
        "echo 'Time = 1'\n"
        "echo 'Solving for p, Initial residual = 1e-3, Final residual = 1e-6'\n"
        "mkdir -p 1\n"
        "cp 0/p 1/p\n"
        "cp 0/U 1/U\n"
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
    assert payload["times_seen"] == [1.0]
    smoke_case = Path(str(payload["case"]))
    assert smoke_case != case.resolve()
    assert (smoke_case / "1" / "p").is_file()
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

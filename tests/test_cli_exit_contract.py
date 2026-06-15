"""Lock the documented CLI exit-code contract (0 success / 1 check / 2 usage)."""

from __future__ import annotations

from pathlib import Path

from ofti.app import cli_tools


def _case(root: Path) -> Path:
    (root / "system").mkdir(parents=True)
    (root / "system" / "controlDict").write_text(
        "application simpleFoam;\n",
        encoding="utf-8",
    )
    return root


def _run(argv: list[str]) -> int:
    try:
        return cli_tools.main(argv)
    except SystemExit as exc:  # argparse usage errors call sys.exit(2)
        return int(exc.code or 0)


def test_success_returns_zero(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    assert _run(["version"]) == 0
    assert _run(["knife", "preflight", str(case), "--json"]) == 0


def test_failed_check_returns_one(tmp_path: Path) -> None:
    # A bare case is missing fvSchemes/fvSolution/mesh, so doctor reports errors.
    case = _case(tmp_path / "case")
    assert _run(["knife", "doctor", str(case), "--json"]) == 1


def test_output_mode_conflict_returns_two(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    assert _run(["knife", "doctor", str(case), "--json", "--table"]) == 2


def test_unknown_profile_returns_two(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    assert _run(["knife", "physical", str(case), "--profile", "nope", "--json"]) == 2


def test_unknown_preset_returns_two(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    assert _run(["knife", "compare-fields", str(case), str(case), "--preset", "nope", "--json"]) == 2


def test_invalid_usage_returns_two() -> None:
    assert _run(["knife", "compare"]) == 2  # missing required arguments
    assert _run(["knife", "bogus"]) == 2  # invalid subcommand
    assert _run(["knife", "doctor", "--bogus"]) == 2  # unrecognized flag

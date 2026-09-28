from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ofti.core import decomposition
from ofti.tools.cli_tools import run as run_ops

# Shape of the OpenFOAM v2206 cavity tutorial decomposeParDict.
_HIERARCHICAL = """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      decomposeParDict;
}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

numberOfSubdomains  9;

method  hierarchical;

coeffs
{
    n   (3 3 1);   // x y z
}
"""


@pytest.mark.parametrize(
    ("ranks", "current", "expected"),
    [
        (2, (3, 3, 1), (2, 1, 1)),
        (4, (3, 3, 1), (2, 2, 1)),
        (6, (3, 3, 1), (3, 2, 1)),
        (8, (2, 2, 2), (2, 2, 2)),
        (12, (4, 1, 1), (12, 1, 1)),
        (7, None, (7, 1, 1)),
        (4, (1, 1, 1), (2, 2, 1)),
    ],
)
def test_geometric_counts_keep_unused_axes_and_balance_factors(
    ranks: int,
    current: tuple[int, int, int] | None,
    expected: tuple[int, int, int],
) -> None:
    counts = decomposition.geometric_counts(ranks, current)

    assert counts == expected
    assert counts[0] * counts[1] * counts[2] == ranks


def test_rescale_rewrites_n_as_integers_and_keeps_comments() -> None:
    edit = decomposition.rescale_geometric_text(_HIERARCHICAL, ranks=2)

    assert edit is not None
    assert edit.method == "hierarchical"
    assert edit.before == (3, 3, 1)
    assert edit.after == (2, 1, 1)
    assert "n   (2 1 1);   // x y z" in edit.text
    assert "numberOfSubdomains  9;" in edit.text  # only n changes here


@pytest.mark.parametrize("block", ["simpleCoeffs", "hierarchicalCoeffs"])
def test_rescale_handles_legacy_method_coeffs_blocks(block: str) -> None:
    method = block.removesuffix("Coeffs")
    text = f"numberOfSubdomains 4;\nmethod {method};\n{block}\n{{\n    n (4 1 1);\n    delta 0.001;\n}}\n"

    edit = decomposition.rescale_geometric_text(text, ranks=6)

    assert edit is not None
    assert "n (6 1 1);" in edit.text
    assert "delta 0.001;" in edit.text


@pytest.mark.parametrize(
    "text",
    [
        "numberOfSubdomains 2;\nmethod scotch;\n",
        "numberOfSubdomains 2;\nmethod simple;\ncoeffs\n{\n    n (2 1 1);\n}\n",
        "numberOfSubdomains 2;\nmethod hierarchical;\n",
    ],
)
def test_rescale_leaves_consistent_or_non_geometric_dicts_alone(text: str) -> None:
    assert decomposition.rescale_geometric_text(text, ranks=2) is None


def _case(tmp_path: Path, decompose: str = _HIERARCHICAL) -> Path:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "0").mkdir()
    (case / "0" / "U").write_text("internalField uniform (0 0 0);\n")
    (case / "0" / "p").write_text("internalField uniform 0;\n")
    (case / "system" / "controlDict").write_text(
        "FoamFile\n{\n    version 2.0;\n    format ascii;\n    class dictionary;\n    object controlDict;\n}\n"
        "application icoFoam;\n",
    )
    (case / "system" / "decomposeParDict").write_text(decompose)
    return case


def test_parallel_launch_sync_keeps_geometric_decomposition_consistent(tmp_path: Path) -> None:
    case = _case(tmp_path)

    run_ops.solver_command(case, parallel=2, mpi="mpirun", sync_subdomains=True)

    text = (case / "system" / "decomposeParDict").read_text()
    assert decomposition.read_geometric_state(text) == ("hierarchical", (2, 1, 1))
    assert "numberOfSubdomains  2;" in text or "numberOfSubdomains 2;" in text


def test_parallel_launch_sync_fixes_n_even_when_rank_count_already_matches(tmp_path: Path) -> None:
    case = _case(tmp_path, _HIERARCHICAL.replace("numberOfSubdomains  9;", "numberOfSubdomains  2;"))

    run_ops.solver_command(case, parallel=2, mpi="mpirun", sync_subdomains=True)

    assert "n   (2 1 1);" in (case / "system" / "decomposeParDict").read_text()


def test_parallel_launch_without_sync_explains_inconsistent_n(tmp_path: Path) -> None:
    case = _case(tmp_path, _HIERARCHICAL.replace("numberOfSubdomains  9;", "numberOfSubdomains  2;"))

    with pytest.raises(ValueError, match=r"n \(3 3 1\) makes 9 subdomains, not 2"):
        run_ops.solver_command(case, parallel=2, mpi="mpirun", sync_subdomains=False)


def test_prepare_parallel_rescales_n_when_count_already_matches(tmp_path: Path, monkeypatch) -> None:
    # e.g. numberOfSubdomains edited with `knife set`, then queue/smoke prepare the case.
    case = _case(tmp_path, _HIERARCHICAL.replace("numberOfSubdomains  9;", "numberOfSubdomains  2;"))
    commands: list[list[str]] = []
    monkeypatch.setattr(
        run_ops,
        "execute_case_command",
        lambda _case, _name, cmd, **_k: commands.append(list(cmd)) or SimpleNamespace(returncode=0),
    )

    payload = run_ops.prepare_parallel_case(case, parallel=2)

    assert commands == [["decomposePar", "-force"]]
    assert "n   (2 1 1);" in (case / "system" / "decomposeParDict").read_text()
    assert payload["geometric_n"] == {"method": "hierarchical", "before": [3, 3, 1], "after": [2, 1, 1]}


def test_prepare_parallel_leaves_mismatched_counts_and_dry_runs_alone(tmp_path: Path) -> None:
    case = _case(tmp_path)  # numberOfSubdomains 9 vs 2 requested: not guessed here

    assert run_ops.prepare_parallel_case(case, parallel=2, dry_run=True)["geometric_n"] is None
    assert "n   (3 3 1);" in (case / "system" / "decomposeParDict").read_text()

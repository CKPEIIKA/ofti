from __future__ import annotations

import json
from pathlib import Path

import pytest

from ofti.app import cli_tools
from ofti.core.sample_metric import read_numeric_rows, threshold_crossing
from ofti.tools.sample_metric_service import field_metric_payload, metric_payload


def _write_field(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
FoamFile
{
    format ascii;
    class volScalarField;
    object p;
}
dimensions [0 2 -2 0 0 0 0];
internalField nonuniform List<scalar>
3
(
    1
    2
    6
);
boundaryField
{
    wall
    {
        type fixedValue;
        value nonuniform List<scalar>
        2
        (
            4
            8
        );
    }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_series_metric_reports_recent_span_and_maturity(tmp_path: Path) -> None:
    case = tmp_path / "case"
    source = case / "postProcessing" / "probes" / "0" / "p"
    source.parent.mkdir(parents=True)
    source.write_text("# Time p\n0 10\n1 10.10\n2 10.15\n", encoding="utf-8")

    payload = metric_payload(
        case,
        "postProcessing/probes/0/p",
        name="stagnation-p",
        value_column=1,
        window=2,
        max_span=0.1,
    )

    assert payload["mode"] == "series"
    assert payload["value"] == pytest.approx(10.15)
    assert payload["last_n_span"] == pytest.approx(0.05)
    assert payload["mature"] is True
    assert payload["sample_count"] == 3


def test_crossing_metric_tracks_profiles_by_numeric_time(tmp_path: Path) -> None:
    case = tmp_path / "case"
    first = case / "postProcessing" / "sets" / "1" / "line_p.xy"
    second = case / "postProcessing" / "sets" / "2" / "line_p.xy"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("0 0\n1 1\n", encoding="utf-8")
    second.write_text("0 0\n1 0.9\n", encoding="utf-8")

    payload = metric_payload(
        case,
        "postProcessing/sets/*/line_p.xy",
        name="shock-x",
        value_column=1,
        threshold=0.5,
        window=2,
        max_span=0.1,
    )

    assert payload["mode"] == "crossing"
    assert payload["coordinate"] == 2.0
    assert payload["value"] == pytest.approx(5 / 9)
    assert payload["last_n_span"] == pytest.approx(1 / 18)
    assert payload["mature"] is True


def test_metric_requires_explicit_stationarity_limit(tmp_path: Path) -> None:
    case = tmp_path / "case"
    source = case / "probe.dat"
    case.mkdir()
    source.write_text("0 1\n1 1\n", encoding="utf-8")

    payload = metric_payload(case, "probe.dat", value_column=1, window=2)

    assert payload["mature"] is None
    assert payload["maturity_reason"] == "not evaluated; set --max-span"


def test_metric_rejects_source_escape_and_nonfinite_data(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    with pytest.raises(ValueError, match="case-relative"):
        metric_payload(case, "../outside.dat")

    source = case / "probe.dat"
    source.write_text("0 nan\n", encoding="utf-8")
    with pytest.raises(ValueError, match="nonfinite"):
        metric_payload(case, "probe.dat")


def test_threshold_crossing_supports_direction_and_pick(tmp_path: Path) -> None:
    source = tmp_path / "profile.xy"
    source.write_text("0 0\n1 1\n2 0\n", encoding="utf-8")
    rows = read_numeric_rows(source)

    assert threshold_crossing(
        rows,
        coordinate_column=0,
        value_column=1,
        threshold=0.5,
        direction="rising",
    ) == pytest.approx(0.5)
    assert threshold_crossing(
        rows,
        coordinate_column=0,
        value_column=1,
        threshold=0.5,
        pick="last",
    ) == pytest.approx(1.5)
    assert (
        threshold_crossing(
            [(0.0, 0.5), (1.0, 1.0)],
            coordinate_column=0,
            value_column=1,
            threshold=0.5,
            direction="falling",
        )
        is None
    )
    with pytest.raises(ValueError, match="direction"):
        threshold_crossing(rows, coordinate_column=0, value_column=1, threshold=0.5, direction="sideways")


def test_metric_cli_emits_stable_json(tmp_path: Path, capsys) -> None:
    case = tmp_path / "case"
    source = case / "postProcessing" / "probes" / "0" / "p"
    source.parent.mkdir(parents=True)
    source.write_text("0 1\n1 1.01\n", encoding="utf-8")

    code = cli_tools.main(
        [
            "knife",
            "metric",
            str(case),
            "postProcessing/probes/0/p",
            "--name",
            "probe-p",
            "--value-column",
            "1",
            "--window",
            "2",
            "--max-span",
            "0.1",
            "--json",
        ],
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["command"] == "knife metric"
    assert payload["name"] == "probe-p"
    assert payload["mature"] is True


def test_field_metric_reduces_internal_and_patch_values(tmp_path: Path) -> None:
    case = tmp_path / "case"
    _write_field(case / "2" / "p")

    internal = field_metric_payload(case, "p", reduction="mean")
    patch = field_metric_payload(case, "p", patch="wall", reduction="max")

    assert internal["mode"] == "field"
    assert internal["time"] == "2"
    assert internal["value"] == pytest.approx(3.0)
    assert internal["min"] == pytest.approx(1.0)
    assert internal["max"] == pytest.approx(6.0)
    assert internal["finite_count"] == 3
    assert internal["ok"] is True
    assert patch["value"] == pytest.approx(8.0)
    assert patch["value_count"] == 2


def test_field_metric_selects_vector_magnitude_or_component(tmp_path: Path) -> None:
    case = tmp_path / "case"
    field = case / "0" / "U"
    field.parent.mkdir(parents=True)
    field.write_text(
        "internalField nonuniform List<vector> 2 ((3 4 0) (0 0 12));\nboundaryField {}\n",
        encoding="utf-8",
    )

    magnitude = field_metric_payload(case, "U", reduction="mean")
    component = field_metric_payload(case, "U", reduction="max", component="2")

    assert magnitude["component"] == "magnitude"
    assert magnitude["value"] == pytest.approx(8.5)
    assert component["component"] == "2"
    assert component["value"] == pytest.approx(12.0)


def test_field_metric_cli_is_scriptable_and_rejects_ambiguous_sources(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = tmp_path / "case"
    _write_field(case / "1" / "p")

    code = cli_tools.main(
        ["knife", "metric", str(case), "--field", "p", "--reduction", "min", "--json"],
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["command"] == "knife metric"
    assert payload["value"] == pytest.approx(1.0)
    assert payload["field"] == "p"

    code = cli_tools.main(
        ["knife", "metric", str(case), "probe.dat", "--field", "p", "--json"],
    )
    error = capsys.readouterr().err

    assert code == 2
    assert "exactly one" in error


def test_field_metric_reports_nonfinite_values_with_failure_status(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = tmp_path / "case"
    field = case / "0" / "p"
    field.parent.mkdir(parents=True)
    field.write_text(
        "internalField nonuniform List<scalar> 2 (1 nan);\nboundaryField {}\n",
        encoding="utf-8",
    )

    code = cli_tools.main(["knife", "metric", str(case), "--field", "p", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["ok"] is False
    assert payload["value"] == pytest.approx(1.0)
    assert payload["nonfinite_count"] == 1

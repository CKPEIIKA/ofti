from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ofti.core.field_io import flat_values, read_field_values, resolve_time_dir
from ofti.plugins import ProfileMatch

from .field_boundaries import field_boundary_patches, patch_value_summary

AIR5_SPECIES = ("N2", "O2", "NO", "N", "O")
AIR11_SPECIES = (*AIR5_SPECIES, "N2+", "O2+", "NO+", "N+", "O+", "e-")
CORE_FIELDS = ("Tt", "Tv", "Tov", "p", "rho", "e", "ev")
# Transport quantities gathered for scanning.
TRANSPORT_PREFIXES = ("Dmix", "rhoD", "J")
TRANSPORT_FIELDS = ("qDiff", "wallHeatFlux")
# Sign classification: diffusion coefficients (Dmix*, rhoD*) are nonnegative, but
# diffusion-flux components (J_*) and heat fluxes (qDiff, wallHeatFlux) are signed
# and only checked for finiteness. Species mass fractions are bounded to [0, 1].
NONNEGATIVE_PREFIXES = ("Dmix", "rhoD")
_FRACTION_TOL = 1e-8


class Hy2FoamPhysicalProfile:
    name = "hy2foam"

    def detect(self, case_dir: Path) -> ProfileMatch:
        control = case_dir / "system" / "controlDict"
        text = control.read_text(encoding="utf-8", errors="ignore") if control.is_file() else ""
        if "hy2Foam" in text:
            return ProfileMatch(
                confidence=0.9,
                reasons=("controlDict application mentions hy2Foam",),
            )
        return ProfileMatch(confidence=0.0, reasons=("hy2Foam solver marker not found",))

    def fields(self, case_dir: Path) -> list[str]:
        return hy2foam_default_fields(case_dir)

    def rules(self, case_dir: Path) -> list[str]:
        return [_field_rule(name) for name in hy2foam_default_fields(case_dir)]

    def diagnostics(self, case_dir: Path, *, time_name: str = "latest") -> dict[str, Any]:
        """Whole-field checks beyond per-field rules: species sum and 2T ratio."""
        time_dir = resolve_time_dir(case_dir, time_name)
        species = tuple(name for name in AIR11_SPECIES if (time_dir / name).is_file())
        species_sum: dict[str, Any] = (
            species_sum_diagnostic(time_dir, species)
            if len(species) >= 2
            else {"checked": False, "reason": "fewer than two species fields"}
        )
        two_temperature = two_temperature_diagnostic(time_dir, tv_tt_min=0.02, tv_tt_max=50.0)
        violations: list[dict[str, Any]] = []
        deviation = species_sum.get("max_abs_deviation") if species_sum.get("checked") else None
        if deviation is not None and deviation > _FRACTION_TOL:
            violations.append({"field": "sum(Y)", "kind": "species_sum", **species_sum})
        if two_temperature.get("checked") and not two_temperature.get("ok", True):
            violations.append(
                {"field": "Tv/Tt", "kind": "two_temperature_ratio", **two_temperature},
            )
        return {
            "species_sum": species_sum,
            "two_temperature": two_temperature,
            "violations": violations,
        }


def hy2foam_default_fields(case_dir: Path, *, time_name: str = "latest") -> list[str]:
    time_dir = resolve_time_dir(case_dir, time_name)
    present = {path.name for path in time_dir.iterdir() if path.is_file()}
    wanted = [*CORE_FIELDS]
    wanted.extend(name for name in AIR11_SPECIES if name in present)
    wanted.extend(
        name
        for name in sorted(present)
        if name in TRANSPORT_FIELDS or name.startswith(TRANSPORT_PREFIXES)
    )
    return _unique(wanted)


def physical_diagnostics_payload(
    case_dir: Path,
    *,
    time_name: str = "latest",
    species: tuple[str, ...] = AIR5_SPECIES,
    tv_tt_min: float = 0.02,
    tv_tt_max: float = 50.0,
    patches: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    time_dir = resolve_time_dir(case_dir, time_name)
    fields = hy2foam_default_fields(case_dir, time_name=time_name)
    violations: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for name in fields:
        path = time_dir / name
        if not path.is_file():
            continue
        values = _read_flat(path)
        summary = _summary(name, values)
        summaries.append(summary)
        if summary["nonfinite_count"]:
            violations.append(
                {"field": name, "kind": "nonfinite", "count": summary["nonfinite_count"]},
            )
        if _must_be_nonnegative(name) and summary["min"] is not None and summary["min"] < 0.0:
            violations.append({"field": name, "kind": "min>=0", "min": summary["min"]})
        if name in AIR11_SPECIES and _fraction_out_of_bounds(summary):
            violations.append(
                {
                    "field": name,
                    "kind": "fraction",
                    "min": summary["min"],
                    "max": summary["max"],
                },
            )
    species_sum = species_sum_diagnostic(time_dir, species)
    if species_sum["checked"] and species_sum.get("max_abs_deviation", 0.0) > 1e-8:
        violations.append({"field": "sum(Y)", "kind": "species_sum", **species_sum})
    two_temperature = two_temperature_diagnostic(
        time_dir,
        tv_tt_min=tv_tt_min,
        tv_tt_max=tv_tt_max,
    )
    if two_temperature["checked"] and not two_temperature["ok"]:
        violations.append({"field": "Tv/Tt", "kind": "two_temperature_ratio", **two_temperature})
    patch_ranges = patch_range_diagnostics(time_dir, fields, patches=patches)
    for row in patch_ranges:
        if row["nonfinite_count"]:
            violations.append(
                {
                    "field": row["field"],
                    "patch": row["patch"],
                    "kind": "patch_nonfinite",
                    "count": row["nonfinite_count"],
                },
            )
    return {
        "case": str(case_dir),
        "time": time_dir.name,
        "ok": True,
        "physical_ok": not violations,
        "fields": summaries,
        "violations": violations,
        "diagnostics": {
            "species_sum": species_sum,
            "two_temperature": two_temperature,
            "patch_ranges": patch_ranges,
        },
    }


def patch_range_diagnostics(
    time_dir: Path,
    fields: list[str],
    *,
    patches: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    wanted = set(patches or ())
    summaries: list[dict[str, Any]] = []
    for name in fields:
        path = time_dir / name
        if not path.is_file():
            continue
        field_patches = field_boundary_patches(path)
        for patch in field_patches:
            patch_name = patch["patch"]
            if wanted and patch_name not in wanted:
                continue
            try:
                summary = patch_value_summary(path, patch_name)
            except ValueError:
                continue
            summary["boundary_type"] = patch["type"]
            summaries.append(summary)
    return summaries


def species_sum_diagnostic(time_dir: Path, species: tuple[str, ...]) -> dict[str, Any]:
    missing = [name for name in species if not (time_dir / name).is_file()]
    if missing:
        return {"checked": False, "reason": "missing species fields", "missing": missing}
    values_by_name = {name: _read_flat(time_dir / name) for name in species}
    counts = {len(values) for values in values_by_name.values()}
    if len(counts) != 1:
        return {"checked": False, "reason": "species field counts differ", "fields": list(species)}
    totals = [
        sum(values[index] for values in values_by_name.values())
        for index in range(counts.pop())
    ]
    deviations = [abs(value - 1.0) for value in totals if math.isfinite(value)]
    return {
        "checked": True,
        "fields": list(species),
        "count": len(totals),
        "min": min(totals) if totals else None,
        "max": max(totals) if totals else None,
        "max_abs_deviation": max(deviations) if deviations else None,
        "tolerance": 1e-8,
    }


def two_temperature_diagnostic(
    time_dir: Path,
    *,
    tv_tt_min: float,
    tv_tt_max: float,
) -> dict[str, Any]:
    if not (time_dir / "Tv").is_file() or not (time_dir / "Tt").is_file():
        return {"checked": False, "reason": "Tv or Tt missing"}
    tv = _read_flat(time_dir / "Tv")
    tt = _read_flat(time_dir / "Tt")
    count = min(len(tv), len(tt))
    ratios = [tv[index] / tt[index] for index in range(count) if tt[index] > 0.0]
    bad = [value for value in ratios if value < tv_tt_min or value > tv_tt_max]
    return {
        "checked": True,
        "ok": not bad,
        "count": count,
        "ratio_min": min(ratios) if ratios else None,
        "ratio_max": max(ratios) if ratios else None,
        "bad_count": len(bad),
        "expected_range": [tv_tt_min, tv_tt_max],
    }


def _read_flat(path: Path) -> list[float]:
    return flat_values(read_field_values(path).values)


def _summary(name: str, values: list[float]) -> dict[str, Any]:
    finite = [value for value in values if math.isfinite(value)]
    return {
        "field": name,
        "count": len(values),
        "min": min(finite) if finite else None,
        "max": max(finite) if finite else None,
        "nonfinite_count": len(values) - len(finite),
    }


def _field_rule(name: str) -> str:
    if name in AIR11_SPECIES:
        return f"{name}:min=0,max=1"
    if _must_be_nonnegative(name):
        return f"{name}:min=0"
    return name  # signed quantity (J_*, qDiff, wallHeatFlux): finiteness only


def _must_be_nonnegative(name: str) -> bool:
    return name in CORE_FIELDS or name.startswith(NONNEGATIVE_PREFIXES)


def _fraction_out_of_bounds(summary: dict[str, Any]) -> bool:
    minimum = summary["min"]
    maximum = summary["max"]
    if minimum is None or maximum is None:
        return False
    return minimum < 0.0 or maximum > 1.0 + _FRACTION_TOL


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result

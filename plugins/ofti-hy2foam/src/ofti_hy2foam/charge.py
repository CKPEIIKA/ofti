from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ofti.core.field_io import flat_values, read_field_values, resolve_time_dir

from .field_boundaries import field_boundary_patches, wall_patch_names

ELECTRON_MASS_KG = 9.1093837015e-31
ION_SPECIES = ("N2+", "O2+", "NO+", "N+", "O+")
ELECTRON_FIELDS = ("e-", "E")


class Hy2FoamChargeCommand:
    name = "charge"

    def add_parser(self, subparsers) -> None:
        parser = subparsers.add_parser("charge", help="Report hy2Foam charge observability")
        parser.add_argument("case_dir", type=Path)
        parser.add_argument("--time", default="latest")
        parser.set_defaults(func=self.run)

    def run(self, args) -> int:
        payload = charge_payload(args.case_dir, time_name=str(getattr(args, "time", "latest")))
        print(f"case={payload['case']}")
        print(f"time={payload['time']}")
        print(f"charged_species={','.join(payload['charged_species'])}")
        print("warning=this is observability only; it does not enable ambipolar diffusion")
        return 0 if payload["ok"] else 1


def charge_payload(case_dir: Path, *, time_name: str = "latest") -> dict[str, Any]:
    time_dir = resolve_time_dir(case_dir, time_name)
    rho = _optional_flat(time_dir / "rho")
    electron_field = next((name for name in ELECTRON_FIELDS if (time_dir / name).is_file()), None)
    electron_mass_fraction = _optional_flat(time_dir / electron_field) if electron_field else None
    electron_density = _number_density(rho, electron_mass_fraction, ELECTRON_MASS_KG)
    ion_density: dict[str, dict[str, Any]] = {}
    total_positive = 0.0
    for name in ION_SPECIES:
        values = _optional_flat(time_dir / name)
        density = _number_density(rho, values, _ion_mass_placeholder(name))
        if density["available"]:
            ion_density[name] = density
            total_positive += float(density["sum"] or 0.0)
    electron_total = float(electron_density["sum"] or 0.0) if electron_density["available"] else 0.0
    imbalance = total_positive - electron_total
    ratio = abs(imbalance) / total_positive if total_positive > 0.0 else None
    charged_species = [*ion_density]
    if electron_field:
        charged_species.append(electron_field)
    wall_boundary_types = charged_wall_boundary_types(case_dir, time_dir, charged_species)
    return {
        "case": str(case_dir),
        "time": time_dir.name,
        "ok": True,
        "charged_species": charged_species,
        "electron_field": electron_field,
        "electron_number_density": electron_density,
        "positive_ion_number_density": ion_density,
        "net_charge_number_density_sum": imbalance,
        "max_abs_net_over_positive_sum": ratio,
        "charged_wall_boundary_types": wall_boundary_types,
        "warnings": [
            "charge diagnostics are observational only",
            "charged species do not imply ambipolar diffusion is configured",
        ],
    }


def charged_wall_boundary_types(
    case_dir: Path,
    time_dir: Path,
    charged_species: list[str],
) -> list[dict[str, str]]:
    paths = [time_dir / name for name in charged_species]
    wall_patches = wall_patch_names(case_dir, field_paths=paths)
    rows: list[dict[str, str]] = []
    for path in paths:
        for patch in field_boundary_patches(path):
            patch_name = patch["patch"]
            if wall_patches and patch_name not in wall_patches:
                continue
            if not wall_patches and "wall" not in patch_name.lower():
                continue
            rows.append({"field": path.name, "patch": patch_name, "type": patch["type"]})
    return rows


def _number_density(
    rho: list[float] | None,
    mass_fraction: list[float] | None,
    particle_mass: float,
) -> dict[str, Any]:
    if rho is None or mass_fraction is None:
        return {"available": False, "reason": "rho or species field missing"}
    count = min(len(rho), len(mass_fraction))
    values = [rho[index] * mass_fraction[index] / particle_mass for index in range(count)]
    finite = [value for value in values if math.isfinite(value)]
    return {
        "available": True,
        "count": count,
        "min": min(finite) if finite else None,
        "max": max(finite) if finite else None,
        "sum": sum(finite),
    }


def _optional_flat(path: Path | None) -> list[float] | None:
    if path is None or not path.is_file():
        return None
    return flat_values(read_field_values(path).values)


def _ion_mass_placeholder(name: str) -> float:
    # Relative charge observability only; exact masses belong in a fuller chemistry profile.
    mass_numbers = {"N2+": 28.0, "O2+": 32.0, "NO+": 30.0, "N+": 14.0, "O+": 16.0}
    atomic_mass_kg = 1.66053906660e-27
    return mass_numbers[name] * atomic_mass_kg

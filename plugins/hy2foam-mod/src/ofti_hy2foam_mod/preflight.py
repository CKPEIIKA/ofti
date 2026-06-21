from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ofti.core.command_spec import ArgumentSpec, CommandSpec, OptionSpec
from ofti.core.output_contract import command_name, stamp_payload

# NN-fork species / state ordering keys, extracted out of the stock plugin.
NN_SPECIES_ORDER_KEYS = ("stateInputOrder", "inputOrder", "outputOrder")
# Air-11 species recognised inside an ordering tuple (state variables such as
# p/Tt/Tv are ignored so the comparison is over the species subsequence).
_AIR_SPECIES = (
    "N2", "O2", "NO", "N", "O", "N2+", "O2+", "NO+", "N+", "O+", "e-",
)


class Hy2FoamModPreflightCommand:
    name = "hy2foam-mod-preflight"

    def command_spec(self) -> CommandSpec:
        return CommandSpec(
            name="hy2foam-mod-preflight",
            summary="Check NN-fork hy2Foam species/state ordering consistency",
            handler=self.run,
            arguments=(ArgumentSpec("case_dir", type=Path),),
            options=(OptionSpec(("--json",), action="store_true"),),
        )

    def run(self, args) -> int:
        payload = nn_preflight_payload(args.case_dir)
        if bool(getattr(args, "json", False)):
            print(json.dumps(stamp_payload(payload, command_name(args)), indent=2, sort_keys=True))
            return 0 if payload["ok"] else 1
        check = payload["check"]
        print(f"case={payload['case']}")
        print(f"ok={payload['ok']}")
        print(f"{check['name']}={check['status']} {check['detail']}")
        return 0 if payload["ok"] else 1


def nn_preflight_payload(case_dir: Path) -> dict[str, Any]:
    check = nn_species_order_consistency_check(case_dir)
    return {
        "case": str(case_dir),
        "ok": check["status"] != "FAIL",
        "check": check,
    }


def nn_species_order_consistency_check(case_dir: Path) -> dict[str, str]:
    orders = nn_species_order_sources(case_dir)
    if len(orders) < 2:
        return _check("nn_species_order_consistency", "WARN", "fewer than two NN-order sources")
    reference = orders[0][2]
    mismatches = [f"{path}:{key}" for path, key, values in orders[1:] if values != reference]
    if mismatches:
        first_path, first_key, _values = orders[0]
        return _check(
            "nn_species_order_consistency",
            "FAIL",
            f"reference={first_path}:{first_key}; mismatches={','.join(mismatches)}",
        )
    return _check("nn_species_order_consistency", "PASS", f"{len(orders)} sources")


def nn_species_order_sources(case_dir: Path) -> list[tuple[str, str, tuple[str, ...]]]:
    """Scan constant/ and system/ for NN-fork ordering tuples."""
    pattern = "|".join(re.escape(key) for key in NN_SPECIES_ORDER_KEYS)
    entry_re = re.compile(rf"\b(?P<key>{pattern})\s*\((?P<body>[^)]*)\)\s*;", re.DOTALL)
    orders: list[tuple[str, str, tuple[str, ...]]] = []
    for root in (case_dir / "constant", case_dir / "system"):
        if not root.is_dir():
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for match in entry_re.finditer(text):
                species = _recognized_species(match.group("body"))
                if len(species) >= 2:
                    orders.append((str(path.relative_to(case_dir)), match.group("key"), species))
    return orders


def _recognized_species(text: str) -> tuple[str, ...]:
    names = re.findall(r"[A-Za-z0-9_+-]+", text)
    return tuple(name for name in names if name in _AIR_SPECIES)


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}

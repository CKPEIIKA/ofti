from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def write_compare_report(payload: dict[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "latest.csv"
    md_path = out_dir / "latest.md"
    _write_rows_csv(csv_path, _compare_csv_rows(payload))
    _write_markdown_table(md_path, _compare_markdown_rows(payload), title="Field Compare")
    return {"csv": str(csv_path), "markdown": str(md_path)}


def write_physical_report(
    payload: dict[str, Any],
    out_dir: Path,
    *,
    stem: str = "physical",
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{stem}.csv"
    md_path = out_dir / f"{stem}.md"
    _write_rows_csv(csv_path, _physical_csv_rows(payload))
    _write_markdown_table(md_path, _physical_markdown_rows(payload), title="Physical Checks")
    return {"csv": str(csv_path), "markdown": str(md_path)}


def _write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown_table(path: Path, rows: list[dict[str, Any]], *, title: str) -> None:
    if not rows:
        path.write_text(f"# {title}\n\nNo rows.\n", encoding="utf-8")
        return
    keys = list(rows[0])
    lines = [
        f"# {title}",
        "",
        "| " + " | ".join(keys) + " |",
        "| " + " | ".join("---" for _ in keys) + " |",
    ]
    lines.extend("| " + " | ".join(_cell(row.get(key)) for key in keys) + " |" for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _compare_csv_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    keys = [
        "field",
        "n",
        "reference_min",
        "reference_max",
        "candidate_min",
        "candidate_max",
        "abs_linf",
        "rel_l2",
        "rel_linf",
        "rel_linf_significant",
        "ratio_min",
        "ratio_p05",
        "ratio_median",
        "ratio_p95",
        "ratio_max",
        "nonfinite_pairs",
        "error",
    ]
    return [{key: row.get(key) for key in keys} for row in payload.get("fields", [])]


def _compare_markdown_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    keys = ["field", "n", "rel_l2", "rel_linf_significant", "abs_linf", "nonfinite_pairs", "error"]
    return [{key: row.get(key) for key in keys} for row in payload.get("fields", [])]


def _physical_csv_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    violations = {
        row.get("field"): row
        for row in payload.get("violations", [])
        if isinstance(row, dict)
    }
    rows: list[dict[str, Any]] = []
    for row in payload.get("fields", []):
        if not isinstance(row, dict):
            continue
        violation = violations.get(row.get("field"))
        rows.append(
            {
                "field": row.get("field"),
                "check": violation.get("kind") if isinstance(violation, dict) else "finite/default",
                "status": "fail" if violation or row.get("nonfinite_count") else "ok",
                "min": row.get("min"),
                "max": row.get("max"),
                "n_bad": row.get("nonfinite_count") or (violation or {}).get("count", 0),
                "bad_indices_sample": " ".join(
                    str(item) for item in (violation or {}).get("sample", [])
                ),
            },
        )
    return rows


def _physical_markdown_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    keys = ["field", "status", "min", "max", "n_bad"]
    return [{key: row.get(key) for key in keys} for row in _physical_csv_rows(payload)]


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)

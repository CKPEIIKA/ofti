from __future__ import annotations

import re


def extract_last_courant(lines: list[str]) -> float | None:
    patterns = [
        r"(?i)max\s+courant\s+number\s*=\s*([0-9eE.+-]+)",
        r"(?i)courant\s+number.*max:\s*([0-9eE.+-]+)",
        r"(?i)max\s+courant\s+number\s*:\s*([0-9eE.+-]+)",
    ]
    for line in reversed(lines):
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue
    return None


def format_checkmesh_summary(output: str) -> str:
    lower = output.lower()
    mesh_ok = "mesh ok" in lower
    failed = match_first(output, [r"(?i)failed\s+(\d+)\s+mesh checks"])
    errors = "0" if mesh_ok and not failed else failed or "1"
    status = "OK" if mesh_ok and errors == "0" else "FAIL"

    counts = [
        (
            "Cells",
            match_first(
                output,
                [r"(?i)number of cells\s*:\s*(\d+)", r"(?i)cells\s*:\s*(\d+)"] ,
            )
            or "n/a",
        ),
        (
            "Faces",
            match_first(
                output,
                [r"(?i)number of faces\s*:\s*(\d+)", r"(?i)faces\s*:\s*(\d+)"] ,
            )
            or "n/a",
        ),
        (
            "Points",
            match_first(
                output,
                [r"(?i)number of points\s*:\s*(\d+)", r"(?i)points\s*:\s*(\d+)"] ,
            )
            or "n/a",
        ),
        ("Internal faces", match_first(output, [r"(?i)internal faces\s*:\s*(\d+)"]) or "n/a"),
        ("Boundary faces", match_first(output, [r"(?i)boundary faces\s*:\s*(\d+)"]) or "n/a"),
    ]

    quality = [
        (
            "Max non-orth",
            match_first(
                output,
                [
                    r"(?i)max\s+non-orthogonality\s*=\s*([0-9eE.+-]+)",
                    r"(?i)non-orthogonality.*max\s*[:=]\s*([0-9eE.+-]+)",
                    r"(?i)non-orthogonality.*max\s+([0-9eE.+-]+)",
                ],
            )
            or "n/a",
        ),
        (
            "Avg non-orth",
            match_first(
                output,
                [
                    r"(?i)average\s+non-orthogonality\s*=\s*([0-9eE.+-]+)",
                    r"(?i)non-orthogonality.*average\s*[:=]\s*([0-9eE.+-]+)",
                    r"(?i)non-orthogonality.*average\s+([0-9eE.+-]+)",
                ],
            )
            or "n/a",
        ),
        (
            "Max skewness",
            match_first(
                output,
                [
                    r"(?i)max\s+skewness\s*=\s*([0-9eE.+-]+)",
                    r"(?i)skewness.*max\s*[:=]\s*([0-9eE.+-]+)",
                    r"(?i)skewness.*max\s+([0-9eE.+-]+)",
                ],
            )
            or "n/a",
        ),
        (
            "Max boundary skew",
            match_first(
                output,
                [r"(?i)max\s+boundary\s+skewness\s*=\s*([0-9eE.+-]+)"],
            )
            or "n/a",
        ),
        (
            "Max internal skew",
            match_first(
                output,
                [r"(?i)max\s+internal\s+skewness\s*=\s*([0-9eE.+-]+)"],
            )
            or "n/a",
        ),
        (
            "Max aspect ratio",
            match_first(output, [r"(?i)max\s+aspect\s+ratio\s*=\s*([0-9eE.+-]+)"])
            or "n/a",
        ),
        (
            "Max cell openness",
            match_first(output, [r"(?i)max\s+cell\s+openness\s*=\s*([0-9eE.+-]+)"])
            or "n/a",
        ),
        ("Min volume", match_first(output, [r"(?i)min\s+volume\s*=\s*([0-9eE.+-]+)"]) or "n/a"),
        (
            "Min detJ",
            match_first(output, [r"(?i)min\s+determinant\s*=\s*([0-9eE.+-]+)"])
            or "n/a",
        ),
    ]
    quality = _filter_nonzero(quality)

    fatal_count = len(re.findall(r"(?i)fatal", output))
    notes = [
        f"Status: {status} | Errors: {errors}",
        f"Fatal: {fatal_count}" if fatal_count else "Fatal: 0",
        f"Failed checks: {failed}" if failed else "Failed checks: 0",
    ]

    lines = ["CHECKMESH SUMMARY", ""]
    lines.append("Notes:")
    lines.extend(kv_lines(notes, pad="  ", split=" | "))
    lines.append("")
    lines.append("Counts:")
    lines.extend(format_kv_block(counts, pad="  "))
    lines.append("")
    if quality:
        lines.append("Quality (non-zero):")
        lines.extend(format_kv_block(quality, pad="  "))

    return "\n".join(lines)


def kv_lines(items: list[str], pad: str = "  ", split: str = "") -> list[str]:
    if split:
        return [pad + split.join(items)]
    return [pad + item for item in items]


def format_kv_block(rows: list[tuple[str, str]], pad: str = "  ") -> list[str]:
    if not rows:
        return []
    label_width = max(len(label) for label, _value in rows)
    lines = []
    for label, value in rows:
        lines.append(f"{pad}{label.ljust(label_width)} : {value}")
    return lines


def match_first(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def _filter_nonzero(rows: list[tuple[str, str]]) -> list[tuple[str, str]]:
    kept: list[tuple[str, str]] = []
    for label, value in rows:
        parsed = _as_float(value)
        if parsed is None:
            continue
        if parsed == 0:
            continue
        kept.append((label, value))
    return kept


def _as_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

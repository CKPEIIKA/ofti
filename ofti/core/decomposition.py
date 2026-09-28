"""Keep geometric decompositions consistent with ``numberOfSubdomains``.

``simple`` and ``hierarchical`` decompositions carry ``n (nx ny nz)`` whose
product must equal ``numberOfSubdomains``; decomposePar refuses otherwise. When
OFTI changes the rank count it rescales ``n`` too, editing only that entry so
comments and layout survive. Other methods (scotch, metis, kahip, ...) need no
coefficients and are left untouched.
"""

from __future__ import annotations

import math
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

GEOMETRIC_METHODS = frozenset({"simple", "hierarchical"})
_AXES = 3

_METHOD_RE = re.compile(r"(?m)^\s*method\s+(?P<method>\w+)\s*;")
_N_RE = re.compile(r"\bn(?P<gap>\s*)\((?P<body>[^)]*)\)")

type Counts = tuple[int, int, int]


@dataclass(frozen=True)
class GeometricEdit:
    method: str
    before: Counts
    after: Counts
    text: str


def geometric_counts(ranks: int, current: Counts | None) -> Counts:
    """Split ``ranks`` over the axes ``current`` already divides, balancing factors.

    Axes that were 1 (typically the empty or 2D direction) stay 1. Prime
    factors, largest first, go to the active axis with the smallest product.
    """
    if ranks < 1:
        raise ValueError(f"rank count must be positive, got {ranks}")
    active = [axis for axis, count in enumerate(current or ()) if count > 1] or list(range(_AXES))
    counts = [1, 1, 1]
    for factor in sorted(_prime_factors(ranks), reverse=True):
        axis = min(active, key=lambda index: (counts[index], index))
        counts[axis] *= factor
    return counts[0], counts[1], counts[2]


def read_geometric_state(text: str) -> tuple[str, Counts | None] | None:
    """Return ``(method, n)`` for a geometric decomposition, else None."""
    method = _method(text)
    if method not in GEOMETRIC_METHODS:
        return None
    spans = _n_spans(text, method)
    return method, (_parse_counts(text[spans[0][0] : spans[0][1]]) if spans else None)


def mismatch_reason(text: str, ranks: int) -> str | None:
    """Explain why a geometric ``n`` cannot produce ``ranks`` subdomains, if it can't."""
    state = read_geometric_state(text)
    if state is None:
        return None
    method, counts = state
    if counts is None:
        return None
    product = math.prod(counts)
    if product == ranks:
        return None
    shown = " ".join(str(count) for count in counts)
    return f"decomposeParDict method {method}: n ({shown}) makes {product} subdomains, not {ranks}"


def rescale_geometric_text(text: str, *, ranks: int) -> GeometricEdit | None:
    """Rewrite every ``n`` in the method's coefficient blocks; None when nothing to do."""
    method = _method(text)
    if method not in GEOMETRIC_METHODS:
        return None
    spans = _n_spans(text, method)
    if not spans:
        return None
    before = _parse_counts(text[spans[0][0] : spans[0][1]])
    if before is not None and math.prod(before) == ranks:
        return None
    after = geometric_counts(ranks, before)
    updated = text
    for start, end in reversed(spans):
        match = _N_RE.match(updated, start, end)
        if match is None:
            continue
        replacement = f"n{match.group('gap')}({after[0]} {after[1]} {after[2]})"
        updated = updated[:start] + replacement + updated[end:]
    return GeometricEdit(method, before or (1, 1, 1), after, updated)


def rescale_geometric_file(path: Path, *, ranks: int) -> GeometricEdit | None:
    """Apply :func:`rescale_geometric_text` to ``path``, replacing it atomically."""
    edit = rescale_geometric_text(path.read_text(encoding="utf-8"), ranks=ranks)
    if edit is None:
        return None
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as temp:
            temp.write(edit.text)
        Path(temp_name).replace(path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return edit


def _method(text: str) -> str | None:
    match = _METHOD_RE.search(_strip_comments(text))
    return match.group("method") if match else None


def _n_spans(text: str, method: str) -> list[tuple[int, int]]:
    """Spans of ``n (...)`` inside ``coeffs`` and ``<method>Coeffs`` blocks."""
    spans: list[tuple[int, int]] = []
    for block in ("coeffs", f"{method}Coeffs"):
        for match in re.finditer(rf"(?m)^[ \t]*{block}\s*\{{", text):
            body_start = match.end()
            body_end = _matching_brace(text, body_start)
            n_match = _N_RE.search(text, body_start, body_end)
            if n_match is not None:
                spans.append(n_match.span())
    return sorted(spans)


def _matching_brace(text: str, start: int) -> int:
    depth = 1
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return len(text)


def _parse_counts(n_entry: str) -> Counts | None:
    match = _N_RE.match(n_entry)
    if match is None:
        return None
    try:
        values = [round(float(token)) for token in match.group("body").split()]
    except ValueError:
        return None
    if len(values) != _AXES or any(value < 1 for value in values):
        return None
    return values[0], values[1], values[2]


def _prime_factors(value: int) -> list[int]:
    factors: list[int] = []
    divisor = 2
    remaining = value
    while divisor * divisor <= remaining:
        while remaining % divisor == 0:
            factors.append(divisor)
            remaining //= divisor
        divisor += 1
    if remaining > 1:
        factors.append(remaining)
    return factors


def _strip_comments(text: str) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)

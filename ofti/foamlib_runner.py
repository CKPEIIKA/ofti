from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ofti.foamlib_adapter import FoamlibUnavailableError, available

try:  # pragma: no cover - optional dependency
    from foamlib import FoamCase
except Exception:  # pragma: no cover - optional dependency
    FoamCase = None  # type: ignore[assignment]


def run_case(
    case_path: Path,
    cmd: str | None = None,
    *,
    parallel: bool | None = None,
    cpus: int | None = None,
    check: bool = True,
    log: bool = True,
) -> None:
    if not available() or FoamCase is None:
        raise FoamlibUnavailableError()

    case = FoamCase(case_path)
    case.run(cmd, parallel=parallel, cpus=cpus, check=check, log=log)


def run_cases(
    case_paths: Iterable[Path],
    cmd: str | None = None,
    *,
    parallel: bool | None = None,
    cpus: int | None = None,
    check: bool = True,
    log: bool = True,
) -> list[Path]:
    failures: list[Path] = []
    for case_path in case_paths:
        try:
            run_case(case_path, cmd, parallel=parallel, cpus=cpus, check=check, log=log)
        except Exception:
            failures.append(Path(case_path))
            if check:
                break
    return failures

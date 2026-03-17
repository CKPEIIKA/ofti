from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path

from ofti.foamlib.adapter import FoamlibUnavailableError, available

try:  # pragma: no cover - optional dependency
    from foamlib import AsyncFoamCase, AsyncSlurmFoamCase, FoamCase
except Exception:  # pragma: no cover - optional dependency
    AsyncFoamCase = None  # type: ignore[assignment]
    AsyncSlurmFoamCase = None  # type: ignore[assignment]
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


def decompose_case(
    case_path: Path,
    *,
    check: bool = True,
    log: bool | str = True,
) -> None:
    if not available() or FoamCase is None:
        raise FoamlibUnavailableError()
    case = FoamCase(case_path)
    case.decompose_par(check=check, log=log)


def clean_case(
    case_path: Path,
    *,
    check: bool = False,
) -> None:
    if not available() or FoamCase is None:
        raise FoamlibUnavailableError()
    case = FoamCase(case_path)
    case.clean(check=check)


def copy_case(case_path: Path, destination: Path) -> Path:
    if not available() or FoamCase is None:
        raise FoamlibUnavailableError()
    case = FoamCase(case_path)
    copied = case.copy(destination)
    resolved = Path(getattr(copied, "path", destination))
    return resolved.expanduser().resolve()


def clone_case(case_path: Path, destination: Path) -> Path:
    if not available() or FoamCase is None:
        raise FoamlibUnavailableError()
    case = FoamCase(case_path)
    cloned = case.clone(destination)
    resolved = Path(getattr(cloned, "path", destination))
    return resolved.expanduser().resolve()


def async_available() -> bool:
    return bool(available() and AsyncFoamCase is not None)


def slurm_available() -> bool:
    return bool(available() and AsyncSlurmFoamCase is not None)


async def _run_case_async(
    case_path: Path,
    cmd: str | None,
    *,
    parallel: bool | None,
    cpus: int | None,
    check: bool,
    log: bool | str,
    slurm: bool,
    fallback: bool,
) -> None:
    if slurm:
        if AsyncSlurmFoamCase is None:
            raise FoamlibUnavailableError()
        case = AsyncSlurmFoamCase(case_path)
        await case.run(
            cmd,
            parallel=parallel,
            cpus=cpus,
            check=check,
            log=log,
            fallback=fallback,
        )
        return
    if AsyncFoamCase is None:
        raise FoamlibUnavailableError()
    case = AsyncFoamCase(case_path)
    await case.run(
        cmd,
        parallel=parallel,
        cpus=cpus,
        check=check,
        log=log,
    )


async def _run_cases_async_impl(
    case_paths: list[Path],
    cmd: str | None,
    *,
    parallel: bool | None,
    cpus: int | None,
    check: bool,
    log: bool | str,
    max_parallel: int,
    slurm: bool,
    fallback: bool,
) -> list[Path]:
    if max_parallel <= 0:
        raise ValueError("max_parallel must be > 0")
    failures: list[Path] = []
    if check:
        for case_path in case_paths:
            try:
                await _run_case_async(
                    case_path,
                    cmd,
                    parallel=parallel,
                    cpus=cpus,
                    check=check,
                    log=log,
                    slurm=slurm,
                    fallback=fallback,
                )
            except Exception:
                failures.append(case_path)
                break
        return failures

    sem = asyncio.Semaphore(max_parallel)

    async def _guarded(path: Path) -> tuple[Path, BaseException | None]:
        async with sem:
            try:
                await _run_case_async(
                    path,
                    cmd,
                    parallel=parallel,
                    cpus=cpus,
                    check=check,
                    log=log,
                    slurm=slurm,
                    fallback=fallback,
                )
            except Exception as exc:  # pragma: no cover - exercised via wrapper
                return path, exc
            return path, None

    results = await asyncio.gather(*(_guarded(path) for path in case_paths))
    for path, error in results:
        if error is not None:
            failures.append(path)
    return failures


def run_cases_async(
    case_paths: Iterable[Path],
    cmd: str | None = None,
    *,
    parallel: bool | None = None,
    cpus: int | None = None,
    check: bool = True,
    log: bool | str = True,
    max_parallel: int = 1,
    slurm: bool = False,
    fallback: bool = False,
) -> list[Path]:
    paths = [Path(path) for path in case_paths]
    if not paths:
        return []
    if slurm:
        if not slurm_available():
            raise FoamlibUnavailableError()
    elif not async_available():
        raise FoamlibUnavailableError()
    return asyncio.run(
        _run_cases_async_impl(
            paths,
            cmd,
            parallel=parallel,
            cpus=cpus,
            check=check,
            log=log,
            max_parallel=max_parallel,
            slurm=slurm,
            fallback=fallback,
        ),
    )


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

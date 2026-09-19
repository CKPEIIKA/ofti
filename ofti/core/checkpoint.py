from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.core.times import processor_dirs


class CheckpointError(ValueError):
    @classmethod
    def invalid_processor_count(cls) -> CheckpointError:
        return cls("expected processor count must be positive")

    @classmethod
    def processor_count_mismatch(cls, expected: int, actual: int) -> CheckpointError:
        return cls(f"expected {expected} processor directories, found {actual}")

    @classmethod
    def no_complete_time(cls) -> CheckpointError:
        return cls("no complete decomposed processor time is available to reconstruct")

    @classmethod
    def mpi_size_unknown(cls) -> CheckpointError:
        return cls("unable to determine current MPI size")

    @classmethod
    def resize_target_invalid(cls) -> CheckpointError:
        return cls("target processor count must be greater than 1")

    @classmethod
    def partial_quarantine_unsafe(cls) -> CheckpointError:
        return cls("refusing to quarantine partial times without a complete checkpoint")

    @classmethod
    def quarantine_destination_exists(cls, path: Path) -> CheckpointError:
        return cls(f"quarantine destination already exists: {path}")


def checkpoint_health(case_dir: Path, *, expected_processors: int | None = None) -> dict[str, Any]:
    """Describe decomposed checkpoint completeness without changing the case."""
    processor_paths = processor_dirs(case_dir)
    if expected_processors is not None and expected_processors <= 0:
        raise CheckpointError.invalid_processor_count()
    if expected_processors is not None and len(processor_paths) != expected_processors:
        raise CheckpointError.processor_count_mismatch(expected_processors, len(processor_paths))
    per_processor = {path.name: _processor_times(path) for path in processor_paths}
    all_times = sorted(
        {time_name for values in per_processor.values() for time_name in values},
        key=_time_sort_key,
    )
    complete_times = _complete_processor_times(case_dir, per_processor)
    partial = [_partial_time_row(case_dir, per_processor, time_name) for time_name in all_times]
    partial = [row for row in partial if row["time"] not in complete_times]
    reconstructed = _root_times(case_dir)
    latest_any = all_times[-1] if all_times else None
    latest_complete = complete_times[-1] if complete_times else None
    return {
        "processor_count": len(processor_paths),
        "processor_dirs": [path.name for path in processor_paths],
        "per_processor_times": per_processor,
        "latest_processor_time": latest_any,
        "latest_complete_time": latest_complete,
        "complete_times": complete_times,
        "partial_times": partial,
        "quarantinable_times": [row["time"] for row in partial],
        "reconstructed_times": reconstructed,
        "latest_reconstructed_time": reconstructed[-1] if reconstructed else None,
        "incomplete_latest_discarded": latest_any is not None and latest_any != latest_complete,
        "missing_latest_processors": _missing_processors(per_processor, latest_any),
        "empty_latest_processors": _empty_processors(case_dir, per_processor, latest_any),
    }


def safe_reconstruct_time(health: dict[str, Any]) -> str:
    latest_complete = health.get("latest_complete_time")
    if isinstance(latest_complete, str) and latest_complete:
        return latest_complete
    raise CheckpointError.no_complete_time()


def _processor_times(processor_dir: Path) -> list[str]:
    return sorted(
        (path.name for path in processor_dir.iterdir() if path.is_dir() and _is_time(path.name)),
        key=_time_sort_key,
    )


def _complete_processor_times(case_dir: Path, per_processor: dict[str, list[str]]) -> list[str]:
    if not per_processor:
        return []
    common = set.intersection(*(set(times) for times in per_processor.values()))
    return [
        time_name
        for time_name in sorted(common, key=_time_sort_key)
        if all(_time_dir_has_fields(case_dir / proc / time_name) for proc in per_processor)
    ]


def _partial_time_row(
    case_dir: Path,
    per_processor: dict[str, list[str]],
    time_name: str,
) -> dict[str, Any]:
    return {
        "time": time_name,
        "missing_processors": _missing_processors(per_processor, time_name),
        "empty_processors": _empty_processors(case_dir, per_processor, time_name),
    }


def _missing_processors(per_processor: dict[str, list[str]], time_name: str | None) -> list[str]:
    if time_name is None:
        return []
    return sorted(proc for proc, times in per_processor.items() if time_name not in times)


def _empty_processors(
    case_dir: Path,
    per_processor: dict[str, list[str]],
    time_name: str | None,
) -> list[str]:
    if time_name is None:
        return []
    return sorted(
        proc
        for proc, times in per_processor.items()
        if time_name in times and not _time_dir_has_fields(case_dir / proc / time_name)
    )


def _root_times(case_dir: Path) -> list[str]:
    return sorted(
        (
            path.name
            for path in case_dir.iterdir()
            if path.is_dir() and _is_time(path.name) and _time_dir_has_fields(path)
        ),
        key=_time_sort_key,
    )


def _time_dir_has_fields(time_dir: Path) -> bool:
    try:
        return any(path.is_file() for path in time_dir.rglob("*"))
    except OSError:
        return False


def _is_time(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _time_sort_key(value: str) -> tuple[float, str]:
    return (float(value), value)

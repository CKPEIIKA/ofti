"""Case-aware source discovery for generic sampled scalar metrics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ofti.core.field_io import read_field_values, resolve_time_dir
from ofti.core.sample_metric import (
    MetricSample,
    read_numeric_rows,
    relative_threshold_value,
    series_samples,
    summarize_field_values,
    summarize_metric,
    threshold_crossing,
)
from ofti.tools.case_source_service import require_case_dir


@dataclass(frozen=True, slots=True, kw_only=True)
class MetricOptions:
    name: str = "metric"
    coordinate_column: int = 0
    value_column: int = -1
    threshold: float | None = None
    relative_threshold: float | None = None
    direction: str = "any"
    pick: str = "first"
    window: int = 10
    max_span: float | None = None
    scale: float = 1.0
    offset: float = 0.0


@dataclass(frozen=True, slots=True, kw_only=True)
class FieldMetricOptions:
    time_name: str = "latest"
    patch: str | None = None
    reduction: str = "mean"
    component: str = "magnitude"
    name: str | None = None
    scale: float = 1.0
    offset: float = 0.0


def metric_payload(
    case_dir: Path,
    source: str,
    *,
    options: MetricOptions,
) -> dict[str, object]:
    case = require_case_dir(case_dir)
    files = _source_files(case, source)
    _validate_thresholds(options.threshold, options.relative_threshold)
    warnings: list[str] = []
    resolved_thresholds: dict[str, float] = {}
    if options.threshold is None and options.relative_threshold is None:
        samples = _series_files(
            case,
            files,
            coordinate_column=options.coordinate_column,
            value_column=options.value_column,
            scale=options.scale,
            offset=options.offset,
        )
        mode = "series"
    else:
        samples = _crossing_files(
            case,
            files,
            options=options,
            warnings=warnings,
            resolved_thresholds=resolved_thresholds,
        )
        mode = "crossing"
    payload = summarize_metric(options.name, samples, window=options.window, max_span=options.max_span)
    payload.update(
        {
            "case": str(case),
            "source": source,
            "files": [path.relative_to(case).as_posix() for path in files],
            "mode": mode,
            "threshold": options.threshold,
            "relative_threshold": options.relative_threshold,
            "resolved_thresholds": resolved_thresholds,
            "coordinate_column": options.coordinate_column,
            "value_column": options.value_column,
            "scale": options.scale,
            "offset": options.offset,
            "warnings": warnings,
            "ok": True,
        },
    )
    return payload


def field_metric_payload(
    case_dir: Path,
    field: str,
    *,
    options: FieldMetricOptions,
) -> dict[str, object]:
    case = require_case_dir(case_dir)
    field_name = _field_name(field)
    time_dir = resolve_time_dir(case, options.time_name)
    data = read_field_values(time_dir / field_name, patch=options.patch)
    payload = summarize_field_values(
        data.values,
        reduction=_reduction(options.reduction),
        component=options.component,
        scale=options.scale,
        offset=options.offset,
    )
    payload.update(
        {
            "case": str(case),
            "name": options.name or field_name,
            "source": (time_dir / field_name).relative_to(case).as_posix(),
            "mode": "field",
            "field": field_name,
            "time": time_dir.name,
            "patch": options.patch,
            "kind": data.kind,
            "components": data.component_count,
            "uniform": data.uniform,
            "scale": options.scale,
            "offset": options.offset,
            "warnings": [],
        },
    )
    return payload


def _field_name(field: str) -> str:
    name = field.strip()
    path = Path(name)
    if not name or path.is_absolute() or len(path.parts) != 1 or name in {".", ".."}:
        raise ValueError("--field must be one field name, not a path")
    return name


def _reduction(value: str) -> str:
    if value not in {"min", "max", "mean"}:
        raise ValueError(f"unsupported field reduction: {value}")
    return value


def _source_files(case: Path, source: str) -> list[Path]:
    pattern = source.strip()
    if not pattern:
        raise ValueError("metric source cannot be empty")
    source_path = Path(pattern)
    if source_path.is_absolute() or ".." in source_path.parts:
        raise ValueError("metric source must be a case-relative path or glob")
    files = sorted((path for path in case.glob(pattern) if path.is_file()), key=lambda path: _file_sort_key(case, path))
    if not files:
        raise ValueError(f"metric source matched no files: {source}")
    return files


def _series_files(
    case: Path,
    files: list[Path],
    *,
    coordinate_column: int,
    value_column: int,
    scale: float,
    offset: float,
) -> list[MetricSample]:
    samples: list[MetricSample] = []
    for path in files:
        samples.extend(
            series_samples(
                read_numeric_rows(path),
                source=path.relative_to(case).as_posix(),
                coordinate_column=coordinate_column,
                value_column=value_column,
                scale=scale,
                offset=offset,
            ),
        )
    return samples


def _crossing_files(
    case: Path,
    files: list[Path],
    *,
    options: MetricOptions,
    warnings: list[str],
    resolved_thresholds: dict[str, float],
) -> list[MetricSample]:
    samples: list[MetricSample] = []
    for index, path in enumerate(files):
        rows = read_numeric_rows(path)
        relative = path.relative_to(case).as_posix()
        threshold = _profile_threshold(rows, options)
        resolved_thresholds[relative] = threshold
        crossing = threshold_crossing(
            rows,
            coordinate_column=options.coordinate_column,
            value_column=options.value_column,
            threshold=threshold,
            direction=options.direction,
            pick=options.pick,
        )
        if crossing is None:
            warnings.append(f"no threshold crossing in {relative}")
            continue
        source_time = _source_time(case, path)
        samples.append(
            MetricSample(
                coordinate=float(index) if source_time is None else source_time,
                value=crossing * options.scale + options.offset,
                source=relative,
            ),
        )
    return samples


def _profile_threshold(rows: list[tuple[float, ...]], options: MetricOptions) -> float:
    if options.threshold is not None:
        return options.threshold
    if options.relative_threshold is None:
        raise ValueError("crossing mode requires a threshold")
    return relative_threshold_value(rows, value_column=options.value_column, fraction=options.relative_threshold)


def _validate_thresholds(threshold: float | None, relative_threshold: float | None) -> None:
    if threshold is not None and relative_threshold is not None:
        raise ValueError("--threshold and --relative-threshold are mutually exclusive")
    if relative_threshold is not None and not 0.0 <= relative_threshold <= 1.0:
        raise ValueError("--relative-threshold must be between 0 and 1")


def _file_sort_key(case: Path, path: Path) -> tuple[bool, float, str]:
    source_time = _source_time(case, path)
    return source_time is None, source_time or 0.0, path.relative_to(case).as_posix()


def _source_time(case: Path, path: Path) -> float | None:
    relative = path.relative_to(case)
    for parent in relative.parents:
        try:
            return float(parent.name)
        except ValueError:
            continue
    return None

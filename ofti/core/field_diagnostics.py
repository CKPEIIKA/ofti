from __future__ import annotations

from ofti.core.field_compare import compare_fields_payload
from ofti.core.field_io import (
    FieldData,
    field_summary_row,
    flat_values,
    foamlib_integration,
    latest_time,
    read_field_values,
    read_internal_field,
    resolve_field_names,
    resolve_time_dir,
    unique,
)
from ofti.core.field_presets import builtin_field_preset_map
from ofti.core.field_reports import write_compare_report, write_physical_report
from ofti.core.physical_rules import FieldRule, field_sanity_payload, parse_field_rules

FIELD_PRESETS: dict[str, list[str]] = builtin_field_preset_map()


def split_field_list(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    names: list[str] = []
    for value in values:
        names.extend(part.strip() for part in value.split(",") if part.strip())
    return unique(names)


__all__ = [
    "FIELD_PRESETS",
    "FieldData",
    "FieldRule",
    "compare_fields_payload",
    "field_sanity_payload",
    "field_summary_row",
    "flat_values",
    "foamlib_integration",
    "latest_time",
    "parse_field_rules",
    "read_field_values",
    "read_internal_field",
    "resolve_field_names",
    "resolve_time_dir",
    "split_field_list",
    "write_compare_report",
    "write_physical_report",
]

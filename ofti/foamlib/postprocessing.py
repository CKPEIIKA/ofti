from __future__ import annotations

from pathlib import Path
from typing import Any

POSTPROCESSING_IMPORT_ERROR: str | None = None

try:  # pragma: no cover - optional postprocessing extras
    from foamlib.postprocessing.load_tables import list_function_objects, load_tables
    FOAMLIB_POSTPROCESSING = True
except Exception as exc:  # pragma: no cover - optional fallback
    list_function_objects = None  # type: ignore[assignment]
    load_tables = None  # type: ignore[assignment]
    FOAMLIB_POSTPROCESSING = False
    POSTPROCESSING_IMPORT_ERROR = str(exc)


def available() -> bool:
    return bool(FOAMLIB_POSTPROCESSING)


def availability_error() -> str | None:
    return POSTPROCESSING_IMPORT_ERROR


def list_table_sources(case_path: Path) -> list[dict[str, Any]]:
    _require_postprocessing()
    assert list_function_objects is not None
    case_root = case_path.resolve()
    discovered = list_function_objects(case_root)
    rows: list[dict[str, Any]] = []
    for source_id, source in sorted(discovered.items()):
        times = list(getattr(source, "times", []))
        folder = str(getattr(source, "folder", ""))
        file_name = str(getattr(source, "file_name", ""))
        rows.append(
            {
                "id": source_id,
                "folder": folder,
                "file_name": file_name,
                "time_resolved": bool(getattr(source, "time_resolved", False)),
                "times": times,
                "time_count": len(times),
            },
        )
    return rows


def load_table_source(
    case_path: Path,
    source_id: str,
    *,
    preview_rows: int = 20,
) -> dict[str, Any]:
    _require_postprocessing()
    assert list_function_objects is not None and load_tables is not None
    case_root = case_path.resolve()
    discovered = list_function_objects(case_root)
    source = discovered.get(source_id)
    if source is None:
        raise KeyError(source_id)
    table = load_tables(source, case_root)
    if table is None:
        return {
            "id": source_id,
            "rows": 0,
            "columns": [],
            "preview": "<no data>",
        }
    rows = int(table.shape[0])
    columns = [str(name) for name in list(getattr(table, "columns", []))]
    preview_df = table.head(max(1, preview_rows))
    preview_text = str(preview_df.to_string(index=False))
    return {
        "id": source_id,
        "rows": rows,
        "columns": columns,
        "preview": preview_text,
    }


def _require_postprocessing() -> None:
    if not FOAMLIB_POSTPROCESSING:
        hint = POSTPROCESSING_IMPORT_ERROR or (
            "foamlib postprocessing extras are unavailable. "
            "Install 'foamlib[postprocessing]'."
        )
        raise RuntimeError(hint)

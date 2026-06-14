from .case import (
    detect_mesh_stats,
    detect_parallel_settings,
    detect_solver,
    has_mesh,
    latest_checkmesh_log,
    parse_cells_count,
    parse_max_skewness,
    read_optional_entry,
)
from .case_fingerprint import case_fingerprint
from .case_headers import (
    case_header_candidates,
    detect_case_header_version,
    extract_header_version,
    parse_foamfile_block_version,
    parse_header_comment_version,
)
from .case_snapshot import build_case_snapshot, write_case_snapshot
from .dict_compare import compare_case_dicts
from .entries import Entry, autoformat_value
from .mesh_info import mesh_counts
from .run_manifest import (
    build_run_manifest,
    collect_case_inputs,
    load_run_manifest,
    resolve_manifest_output,
    restore_run_manifest,
    verify_run_manifest,
    write_case_run_manifest,
    write_run_manifest,
)
from .times import latest_time, time_directories
from .versioning import (
    OpenFOAMVersionInfo,
    detect_openfoam_fork,
    detect_version_info,
    get_dict_path,
    is_legacy_version,
    resolve_solver_alias,
    solver_aliases,
)

__all__ = [
    "Entry",
    "OpenFOAMVersionInfo",
    "autoformat_value",
    "build_case_snapshot",
    "build_run_manifest",
    "case_fingerprint",
    "case_header_candidates",
    "collect_case_inputs",
    "compare_case_dicts",
    "detect_case_header_version",
    "detect_mesh_stats",
    "detect_openfoam_fork",
    "detect_parallel_settings",
    "detect_solver",
    "detect_version_info",
    "extract_header_version",
    "get_dict_path",
    "has_mesh",
    "is_legacy_version",
    "latest_checkmesh_log",
    "latest_time",
    "load_run_manifest",
    "mesh_counts",
    "parse_cells_count",
    "parse_foamfile_block_version",
    "parse_header_comment_version",
    "parse_max_skewness",
    "read_optional_entry",
    "resolve_manifest_output",
    "resolve_solver_alias",
    "restore_run_manifest",
    "solver_aliases",
    "time_directories",
    "verify_run_manifest",
    "write_case_run_manifest",
    "write_case_snapshot",
    "write_run_manifest",
]

# Compatibility aliases for callers that imported the old receipt API.
build_run_receipt = build_run_manifest
load_run_receipt = load_run_manifest
resolve_receipt_output = resolve_manifest_output
restore_run_receipt = restore_run_manifest
verify_run_receipt = verify_run_manifest
write_case_run_receipt = write_case_run_manifest
write_run_receipt = write_run_manifest

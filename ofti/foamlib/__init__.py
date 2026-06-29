from __future__ import annotations

from .adapter import (
    FoamlibUnavailableError,
    available,
    change_boundary_patch_type,
    is_field_file,
    is_foam_file,
    list_keywords,
    list_subkeys,
    parse_boundary_file,
    read_entry,
    read_entry_node,
    read_field_entry,
    read_file_dict,
    rename_boundary_field_patch,
    rename_boundary_patch,
    write_entry,
    write_field_entry,
)
from .logs import (
    parse_courant_numbers,
    parse_execution_times,
    parse_residuals,
    parse_time_steps,
)
from .postprocessing import (
    availability_error as postprocessing_availability_error,
)
from .postprocessing import (
    available as postprocessing_available,
)
from .postprocessing import (
    list_table_sources,
    load_table_source,
)
from .runner import (
    async_available as runner_async_available,
)
from .runner import (
    block_mesh_case,
    clean_case,
    clone_case,
    copy_case,
    decompose_case,
    reconstruct_case,
    restore_0_dir,
    run_case,
    run_cases,
    run_cases_async,
)
from .runner import (
    slurm_available as runner_slurm_available,
)


def __getattr__(name: str) -> object:
    if name == "build_parametric_cases":
        from .parametric import build_parametric_cases

        return build_parametric_cases
    raise AttributeError(name)


__all__ = [
    "FoamlibUnavailableError",
    "available",
    "block_mesh_case",
    "build_parametric_cases",
    "change_boundary_patch_type",
    "clean_case",
    "clone_case",
    "copy_case",
    "decompose_case",
    "is_field_file",
    "is_foam_file",
    "list_keywords",
    "list_subkeys",
    "list_table_sources",
    "load_table_source",
    "parse_boundary_file",
    "parse_courant_numbers",
    "parse_execution_times",
    "parse_residuals",
    "parse_time_steps",
    "postprocessing_availability_error",
    "postprocessing_available",
    "read_entry",
    "read_entry_node",
    "read_field_entry",
    "read_file_dict",
    "reconstruct_case",
    "rename_boundary_field_patch",
    "rename_boundary_patch",
    "restore_0_dir",
    "run_case",
    "run_cases",
    "run_cases_async",
    "runner_async_available",
    "runner_slurm_available",
    "write_entry",
    "write_field_entry",
]

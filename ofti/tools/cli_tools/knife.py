from __future__ import annotations

from ofti.tools import knife_service as service

ProcEntry = service.ProcEntry
_DELTA_T_RE = service._DELTA_T_RE
_END_TIME_RE = service._END_TIME_RE

doctor_payload = service.doctor_payload
doctor_exit_code = service.doctor_exit_code
current_payload = service.current_payload
compare_payload = service.compare_payload
copy_payload = service.copy_payload
initials_payload = service.initials_payload
status_payload = service.status_payload
converge_payload = service.converge_payload
stability_payload = service.stability_payload
preflight_payload = service.preflight_payload
set_entry_payload = service.set_entry_payload

_fallback_solver = service._fallback_solver
_running_job_pids = service._running_job_pids
_scan_proc_solver_processes = service._scan_proc_solver_processes
_proc_table = service._proc_table
_launcher_pids_for_case = service._launcher_pids_for_case
_launcher_has_solver_descendant = service._launcher_has_solver_descendant
_has_ancestor = service._has_ancestor
_read_proc_args = service._read_proc_args
_read_proc_ppid = service._read_proc_ppid
_process_role = service._process_role
_args_match_solver = service._args_match_solver
_token_matches_solver = service._token_matches_solver
_targets_case = service._targets_case
_entry_targets_case = service._entry_targets_case
_proc_cwd = service._proc_cwd
_launcher_descendant_targets_case = service._launcher_descendant_targets_case
_path_within = service._path_within
_looks_like_solver_args = service._looks_like_solver_args
_guess_solver_from_args = service._guess_solver_from_args
_runtime_control_snapshot = service._runtime_control_snapshot
_resolve_solver_log = service._resolve_solver_log
_run_time_control_data = service._run_time_control_data
_read_with_local_includes = service._read_with_local_includes
_strip_include_token = service._strip_include_token
_resolve_include_path = service._resolve_include_path
_strip_comments = service._strip_comments
_iter_blocks_recursive = service._iter_blocks_recursive
_iter_named_blocks = service._iter_named_blocks
_parse_block_name = service._parse_block_name
_matching_brace = service._matching_brace
_first_block_body = service._first_block_body
_dedupe_criteria = service._dedupe_criteria
_inline_criteria = service._inline_criteria
_runtime_control_conditions = service._runtime_control_conditions
_runtime_control_block_rows = service._runtime_control_block_rows
_criterion_status = service._criterion_status
_eta_seconds = service._eta_seconds
_is_log_fresh = service._is_log_fresh
_latest_iteration = service._latest_iteration
_first_match = service._first_match
_last_float = service._last_float
_to_float = service._to_float
_collect_floats = service._collect_floats
_band = service._band
_thermo_out_of_range_count = service._thermo_out_of_range_count
_residual_flatline = service._residual_flatline
_extract_series = service._extract_series
_windowed_stability = service._windowed_stability

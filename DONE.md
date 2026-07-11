# DONE

Completed work only. Record meaningful outcomes and validation evidence, newest first.

## 2026-07-11

- Released 0.9.2 test hardening: CI installs the explicit dev group, schema-contract collection works, and tests contain no type-only `assert isinstance(...)` assertions.
- Added real OpenFOAM behavior for executing a manifest-restored case and for the public CLI start/jobs/stop lifecycle; both pass against sourced OpenFOAM 2512.
- Added a generated and source-controlled `ofti(1)` manual, reproducible scdoc build, user-local installer, contract tests, and successful `man -l` rendering.
- Ran real OpenFOAM MPI scenarios on the host: tracked launcher stop, raw launcher adoption/grouping, processor result comparison, reconstruction, and stopped 2-to-3-rank resize.
- Removed the broad app complexity exemption and all broad-test PLR0915 exemptions; remaining debt is attached to named legacy adapter files.
- Included curses and screen adapters in the coverage gate and added behavior-focused terminal tests without omit rules; canonical gate: `999 passed, 48 skipped`, `85.08%` coverage.
- Restored `uv.lock`, added Ruff formatting to the documented gate, and normalized the repository once with the configured formatter.
- Synchronized repository contracts, ignores, work logs, documentation, quality entrypoint, and CI with the shared Python project pattern.
- Made JSON envelope metadata framework-owned so plugins cannot omit or replace command and schema metadata.

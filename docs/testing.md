# Testing Guidelines

OFTI keeps a strict quality gate because the project has several user-facing
surfaces over the same OpenFOAM case state: CLI, TUI, shared services, foamlib
adapter, and optional plugins.

Run the normal gate before publishing changes:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

## Test Intent

New tests must assert behavior, not only coverage. Prefer assertions on stable
contracts:

- command exit code and JSON/table payload
- service payload field and value
- file content, created artifact, or deleted artifact
- process/job state
- rendered line for UI adapters
- expected exception for invalid input

Smoke tests are allowed when the value is "this terminal path does not crash",
but keep them explicit and few.

## Naming

Do not add new files named for coverage gaps, such as:

- `*_coverage.py`
- `*_lowcov.py`
- `*_more.py`
- `*_extra.py`

Use behavior names instead, for example `test_run_queue.py`,
`test_process_scan.py`, or `test_field_io.py`.

## Slow Real-Case Tests

Tests that launch OpenFOAM or use external case trees must be marked
`real_openfoam` and `slow`; they should run only with `--runslow`.

Use real-case tests for critical services, not for UI plumbing. The service
under test should be the same one used by CLI and TUI adapters.

The current service matrix lives in `docs/real_case_coverage.md`.

`tests/test_real_openfoam_profiles.py` accepts external cases through
`OFTI_REAL_PROFILES`. With `OFTI_ENABLE_REAL_CASE_TESTS=1` and no external
profiles, it generates fresh canonical tutorial cases instead. MPI scenarios
probe the launcher first and skip with its concrete failure reason when the
host or sandbox cannot launch ranks.

## Full-project coverage policy

Coverage includes `ofti/app/screens/` and `ofti/ui_curses/`; there is no UI
omit list. Terminal behavior is tested with deterministic fake screens and
key sequences. These tests assert rendered text, dispatched actions, saved
values, and error handling rather than merely executing lines.

Reusable logic still must not hide there. If a screen needs behavior shared with CLI
or another TUI, move it to `ofti/tools` or `ofti/core` and test it there.

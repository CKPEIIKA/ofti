# Test Suite Audit

Date: 2026-07-11

## Snapshot

- Test files scanned: core tests plus both plugin test packages.
- The full suite includes terminal adapters, plugins, and opt-in real-case test definitions.
- The current quality gate requires at least 85% full-project coverage.
- Latest canonical gate: `999 passed, 48 skipped`, coverage `85.08%`.
- Real OpenFOAM MPI adoption, grouped stop, reconstruction, and stopped resize were validated on a host that permits launcher sockets.

## Signals

The suite is broad and useful for regression coverage, but part of it is still
organized around coverage gaps rather than user-facing behavior.

Naming debt:

- Files with `coverage` in the name: 0.
- Files with `lowcov` in the name: 0.
- Files with `extra` in the name: 0.
- Files with `more` in the name: 0.
- Unique coverage/extra/more/lowcov-style files: 0.

Weak-assertion indicators:

- `is not None`: 61 occurrences.
- `is None`: 156 occurrences.
- standalone `pass`: 69 occurrences, mostly fake screen/test doubles.
- `in payload`: 46 occurrences.
- test functions with no direct `assert` or `pytest.raises`: 0.
- tests with a single assertion based on only `None`/`not None`: 0.

Cleanup done after the audit: coverage/lowcov/extra/more-named test files were
renamed to behavior-oriented names. All tests now contain a direct `assert` or
`pytest.raises`, and the single-assertion `None`/`not None` cases were
strengthened with concrete output, command, file, or path contracts.

## Test naming status

The coverage-shaped file-name backlog is clear: no `tests/test*.py` file uses
`coverage`, `lowcov`, `extra`, or `more` in its name. Continue splitting broad
behavior files when touched, but do not introduce coverage-shaped names again.

## Tests with no direct assert/raises

Current AST scan reports none. Keep this at zero unless a test is explicitly
marked as smoke and still asserts a visible effect.

## New complexity ratchet

Ruff now uses stricter thresholds:

```toml
[lint.mccabe]
max-complexity = 7

[lint.pylint]
max-branches = 7
max-statements = 36
```

Because the repository already contains legacy functions above these thresholds,
current offenders are allowlisted in `pyproject.toml`. This is intentional as a
ratchet, not a permanent exemption: new files/functions must stay under the new
limits, and existing allowlist entries should be removed when touched for nearby
work.

Current biggest complexity-debt buckets:

- UI/curses and CLI adapter functions with interactive loops or parser builders.
- Core parsers for OpenFOAM dictionaries/fields/logs.
- Run/watch process ownership and queue handling.
- Named legacy adapter files; the broad `ofti/app/**/*.py` exception has been removed.

## Cleanup policy

1. Do not add new `*_coverage.py`, `*_lowcov.py`, `*_more.py`, or `*_extra.py`
   files just to lift coverage.
2. Prefer behavior-named files: `test_run_queue.py`, `test_process_scan.py`,
   `test_field_io.py`, etc.
3. A test should assert a stable contract: return code, payload field/value,
   file change, rendered line, process state, or exception.
4. Smoke tests are allowed, but they should be explicit and few.
5. When changing a function on the complexity allowlist, either simplify it below
   the threshold or leave a concrete follow-up in TODO.

## Coverage scope review

No application or curses paths are omitted. `ofti/app/screens/*` and
`ofti/ui_curses/*` are measured by the same 85% project gate. Their behavior
tests use fake terminal screens and deterministic key sequences.

Reusable logic remains in `ofti/core`, `ofti/tools`, and the foamlib adapter,
with architecture tests guarding those boundaries. New shared behavior must
not be added to terminal adapters merely because they now have direct coverage.

The contributor-facing policy now lives in `docs/testing.md`.

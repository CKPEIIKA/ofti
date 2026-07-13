# DONE

Completed work only. Record meaningful outcomes and validation evidence, newest first.

## 2026-07-13

- Hardened the 0.9.3 release against the Cheb-Coulomb smoke findings: case copy never executes `Allclean`, smoke edits preserve unrelated numeric text and expose a diff, binary scalar/vector/tensor internal fields decode across decomposed ranks, and OpenFOAM bashrc injection precedes nounset commands.
- Added opt-in OpenFOAM v2512 proofs for serial and two-way decomposed binary fields; both physical checks pass with complete 400-cell scalar/vector data. The complete release gate passes with `1022 passed, 56 skipped`, `85.11%` coverage, both 0.9.3 distributions build, and an isolated Python 3.11 wheel install reports `ofti 0.9.3`.
- Documented a tag-only GitHub release process and stopped presenting the unpublished project as available from PyPI.
- Unified portable archives under `ofti bundle case|set|extract`; extraction now detects case/set manifests, obsolete top-level adapters were removed, JSON command paths and help/docs/manpage were updated, and real bundle tests pass against OpenFOAM v2512.
- Added deterministic `ofti.bundle-set` v1 campaign archives with per-case manifests/hashes, safe staged extraction, CLI/help/schema documentation, and real OpenFOAM execution coverage for every restored case.
- Upgraded the pinned foamlib integration from 1.5.7 to 1.6.2, added a real controlDict round-trip followed by an exact runnable smoke check, and repaired duplicate entries exposed by the stricter parser in the wedge-sphere example.
- Released 0.9.3 with `1011 passed, 54 skipped` and `85.03%` coverage; the 28-test OpenFOAM v2512 toy matrix reports `24 passed, 4 skipped` on host capabilities, and the real foamlib case-operation profile passes.
- Made `run smoke --iterations N` deterministic: adaptive stepping is disabled in the copy, exact logged steps and a matching checkpoint are required, and incomplete parallel writes fail explicitly.
- Removed foamlib boolean string-conversion warnings by mapping OpenFOAM `true/false/yes/no` tokens to booleans before assignment.
- Added fake-solver and real OpenFOAM coverage for exact/adaptive smoke behavior, zero-exit missing checkpoints, and incomplete MPI checkpoints.
- Passed the full gate with `1004 passed, 52 skipped` and `85.04%` coverage; exact serial and two-rank MPI smoke checks also passed against OpenFOAM v2512.

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

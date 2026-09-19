# DONE

Completed work only. Record meaningful outcomes and validation evidence, newest first.

## 2026-09-19

- Removed the deferred `FBT001` ignore: the curses callback now receives its boolean debug flag by keyword, and stdlib-compatible `Path.resolve` test doubles use generic forwarding arguments. Aligning Ruff with Python 3.12 also removed the remaining `TypeAlias` compatibility form; active Ruff, formatting, and Ty checks pass.
- Assessed `../hy2foam-mod/docs/OFTI_INTEGRATION.md` against installed OFTI 0.9.4. Current copy safety, manifest locality, exact-step smoke, and serial/decomposed binary-field toy checks pass on macOS; the documented hy2Foam sampling deadlock cannot be reproduced because its retained case is absent and `hy2Foam` is unavailable. The host-level OpenFOAM MPI dry-run timeout is reproducible and remains an explicit skip.
- Upgraded the pinned `foamlib` integration from 1.6.2 to 1.8.1 and raised the
  supported Python floor to 3.12, matching the upstream release. Ruff, format,
  Ty, and the full suite pass on macOS with Python 3.13.13; the native
  OpenFOAM-v2512 toy suite passes `26 passed, 4 skipped` after a bounded solver
  dry-run skips the host's unusable MPI path.
- Made opt-in real OpenFOAM tests work with the native macOS OpenFOAM app: tools
  resolve through `OFTI_BASHRC` or the standard app layout, smoke/background
  commands source that environment, and process discovery falls back from
  `/proc`/`ps` to `lsof` for constrained macOS hosts. The bundled Mac toy suite
  passes `26 passed, 4 skipped` (MPI socket capability skips); the full gate
  passes with `1087 passed, 56 skipped` at 85.34% coverage.
- Cleared all active Ruff findings, including the project-wide `PLR2004` production/plugin debt, by replacing protocol and domain literals with named constants or structural checks; retained the root-test `PLR2004` exception for readable fixture assertions.
- Removed global ignores for `S101`, `PLW1510`, `S110`, `S112`, `PLC0415`, `ARG001`, and `B023`; narrowed test/lazy-import exceptions and documented six controlled OpenFOAM subprocess `S603` suppressions.
- Reduced the boolean lint suppression from all `FBT` rules to the deferred positional-boolean API rule `FBT001`; boolean positional call sites (`FBT003`) are now keyword-based.
- Full quality gate passes: Ruff, Ruff format, Ty, and `1083 passed, 56 skipped` with 85.45% coverage.

## 2026-07-29

- Removed superseded GUI, foamlib-adoption, plugin-extraction, and test-audit snapshots; current documentation now points directly to maintained contracts and the hy2Foam plugin.
- Prepared OFTI 0.9.4 with the accumulated CLI/runtime hardening, plugin surfaces, field metrics, portable provenance, compact documentation, and authoritative dynamic package metadata; the full gate passes with `1083 passed, 56 skipped` at 85.38% coverage and both distributions verify as `GPL-3.0-or-later`.
- Extended `knife metric` with direct min/max/mean reductions for internal and boundary-patch fields, scalar-safe vector/tensor component selection, nonfinite failure status, and real OpenFOAM binary/internal plus wall-patch coverage.
- Added `bundle case --run-manifest PATH`: external `ofti.run-manifest` v1 provenance is validated, embedded at `.ofti/provenance/run-manifest.json`, hash/build-digest verified after extraction, and exercised with a real OpenFOAM case.
- Updated CLI help, README, detailed docs, real-case coverage, and the generated man page; targeted OpenFOAM 2512 checks pass and the complete gate reports `1083 passed, 56 skipped` at 85.38% coverage.
- Made plugin discovery inspectable through `ofti plugins list|doctor`, added explicit `CommandSpec` surfaces for knife/run/watch/result plus namespaced progress metrics, and documented/tested entry-point source, version, registrations, duplicate claims, and failures.
- Hardened runtime acceptance: smoke now proves exact steps, a clean exit, a nonzero complete and readable checkpoint, and optional reconstruction; status distinguishes seven lifecycle states; restart planning is read-only and reports common/partial times plus MPI consistency before resize.
- Made repeatable dictionary edits one text-preserving transaction with a complete preview diff, fsynced atomic replacements, all-file rollback, immutable transaction manifest/schema, and a latest pointer.
- Validated the new contracts against sourced OpenFOAM 2512: real dictionary-edit smoke, live pause/resume state, three-rank partial-checkpoint planning/quarantine, two-rank smoke/reconstruction, and full 2-to-3-rank resize all pass with no leftover solver/MPI processes.
- Split restart-plan CLI wiring from the oversized run adapter to keep every production module below the 1000-SLOC ratchet; the complete gate passes with `1076 passed, 56 skipped` and 85.38% coverage.
- Replaced `cli_tools.py` private namespace copying and cross-module rebinding with an explicit three-name compatibility surface; handler tests now patch their real adapters and an architecture test prevents dynamic private exports from returning.
- Removed complexity exemptions from the clean menu, recent-task summary, and command-spec option builder; recorded the before/after measurements and ranked remaining debt in `docs/complexity-debt.md`.
- Made `ofti.__version__` authoritative for package metadata and CLI output, unified licensing on `GPL-3.0-or-later`, verified both built distributions, compacted the README, and moved detailed CLI/TUI/release guidance into `docs/`; the gate passes with `1058 passed, 56 skipped` and 85.31% coverage.
- Fixed non-interactive dispatch: `result` reaches its real command group, bare headless TUI launches fail cleanly with exit code 2, and global `--plain`/`--no-tty` guarantees that curses is never entered.
- Made dictionary edits explicit and safe: `knife set` is update-only unless `--insert` is passed, reports normalized before/after values and operation kind, and honors `--dry-run` for positional and transactional forms.
- Removed custom OpenFOAM table false positives from bundle/doctor linting while retaining generic syntax checks, including regression coverage for parenthesized table rows.
- Added generic probe/sample scalar metrics, HPC-compatible bundle case lists, one-step parametric bundle sets, and verified case/run/build provenance in portable case bundles.
- Updated CLI help, README, formats, schemas, and the generated manual; Ruff 0.16.0, formatting, Ty, and the full suite pass with `1045 passed, 56 skipped` and 85.18% coverage.

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

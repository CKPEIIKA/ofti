# TODO

## Foamlib / OFTI split

Principle: upstream `foamlib` stays behind `ofti/foamlib/*`; OFTI-owned logic lives in
`ofti/core/*` and `ofti/tools/*`; CLI/TUI remain thin adapters over shared services.

### Done / in progress now

- [x] Add `ofti/foamlib/runner.py` wrappers for `FoamCase.block_mesh`,
  `FoamCase.reconstruct_par`, and `FoamCase.restore_0_dir`.
- [x] Prefer foamlib for simple `blockMesh` TUI path when no custom flags are needed.
- [x] Prefer foamlib for plain `reconstructPar` TUI path when no custom flags are needed.
- [x] Keep subprocess fallback for custom flags and utility commands outside foamlib scope.
- [x] Add tests for foamlib case-op wrappers and UI fallback behavior.

### Remaining foamlib opportunities

- [x] Use `FoamCase.restore_0_dir()` in safe clean/restore flows where it exactly matches
  `0.orig -> 0` semantics.
- [x] Evaluate `FoamCase.clean()` for an explicit foamlib-clean mode; keep OFTI's current
  explicit safe clean modes separate.
- [x] Use `FoamCase.file(path)` inside the foamlib adapter where it improves case-relative
  dictionary access without leaking foamlib objects upward.
- [x] Use `FoamFile.as_dict(include_header=True)` for structured read-only snapshots/diffs
  where exact formatting is not required.
- [x] Expand `FoamFieldFile` tests for nonuniform fields, patch values, and internal-field
  round trips on non-trivial time directories.
- [x] Expand slow real-case tests for foamlib-backed `blockMesh`, reconstruct, and
  `restore_0_dir` on canonical OpenFOAM cases.
- [x] Re-check foamlib 1.5.7 for a cheap mesh stats API; no complete cells/faces/points
  API exists yet, so keep `checkMesh` parsing.
- [ ] Re-check future foamlib releases for a cheap mesh stats API when upgrading.

### Keep OFTI-owned

- [ ] Run registry and `.ofti/runs` metadata.
- [ ] Adopt/attach external processes and mpirun launcher/rank normalization.
- [ ] Stop/pause/resume/safe-stop and live process discovery.
- [ ] Sequential queue outcome classification.
- [ ] Runtime mutation with snapshots, diffs, and solver reread confirmation.
- [ ] Case doctor/lint semantics and CFD-specific validation rules.
- [ ] CLI/TUI formatting, command routing, and UX payloads.

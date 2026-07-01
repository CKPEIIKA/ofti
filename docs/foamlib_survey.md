# Foamlib Survey (checked against installed 1.5.7)

Foamlib is installed in `.venv` (version 1.5.7). The notes below are based on
local introspection of the package and the current OFTI adapter.

## Core API (foamlib 1.5.7)

- `FoamFile(path)`: read/write OpenFOAM dictionaries with dict-like access.
- `FoamFieldFile(path)`: field file support with `dimensions`, `internal_field`,
  `boundary_field`.
- `FoamCase(path)`: case helper with convenience properties and actions:
  `control_dict`, `fv_schemes`, `fv_solution`, `transport_properties`,
  `turbulence_properties`, `block_mesh_dict`, `decompose_par_dict`, `application`,
  plus actions: `run`, `block_mesh`, `decompose_par`, `reconstruct_par`, `clean`,
  `clone`, `restore_0_dir`.
- Dimension helpers: `DimensionSet`, `Dimensioned`.

## Currently used via `ofti/foamlib/`

- Parse dictionary files (detect `FoamFile` header).
- `list_keywords(file)`: top-level keys.
- `list_subkeys(file, entry)`: nested keys.
- `read_entry(file, key)`: return raw/dumped text.
- `write_entry(file, key, value)`: scalar + uniform vector writes.
- `FoamFieldFile`: field entries in time directories, including `dimensions`,
  `internalField`, and `boundaryField`.
- `node_type_label/node_type_details`: editor type hints using foamlib objects
  (`DimensionSet`, `Dimensioned`, arrays/vectors, sub-dicts).
- Boundary file operations: patch names/types, patch rename, patch type changes,
  and boundary-field patch rename.
- `FoamCase`: run, copy, clone, clean, decompose, reconstruct.
- `AsyncFoamCase` / `AsyncSlurmFoamCase`: queued case execution backends.
- Preprocessing extras: parameter sweeps, CSV/grid studies, and safe dictionary
  assignment helpers for known `system/*` dictionaries.
- Postprocessing extras: table source listing/loading under `postProcessing`.

## Direct integrations already in OFTI

- `ofti/foam/openfoam.py`: legacy compatibility boundary; shared entry IO now
  prefers `ofti/foamlib/adapter.py` first and falls back to generic parsers.
- `ofti/core/boundary.py`: uses foamlib for boundary file parsing.
- `ofti/ui_curses/blockmesh_helper.py`: uses foamlib to read vertices/blocks when available.
- Entry type detection (`ofti/core/entry_meta.py`) and syntax check flows prefer foamlib.

## Confirmed extras (from introspection)

- `FoamCase.run()` can execute a case end-to-end using heuristics:
  `Allrun`/`run` scripts, `blockMesh`, `restore_0_dir`, `decompose_par`, solver run,
  with optional parallel detection and `log.*` handling.
- `FoamCase.clean()` can clean logs/time/processor/mesh using heuristics or `Allclean`.
- `FoamCase.TimeDirectory` exposes `cell_centers()` helper (reconstructed cases).

OFTI does not expose `FoamCase.clean()` as a broad user-facing clean command.
OFTI cleanup flags are deliberately narrow and explicit: processor-directory
cleanup, log/runtime hygiene around run preparation, and safety snapshots before
destructive workflows. This keeps foamlib's useful heuristic helper separate
from OFTI's predictable CLI behavior.

## Still not covered by foamlib 1.5.7 / remaining TODO

- Mesh stats (cells/faces/points) extraction without `checkMesh`: foamlib 1.5.7
  exposes `TimeDirectory.cell_centers()` but not a complete cheap mesh-info API.
- Dictionary AST/formatting guarantees for exact round-trip stability: OFTI uses
  foamlib for semantic writes, but preserves text fallbacks for cases where exact
  formatting or unsupported syntax matters.
- Runtime process ownership, adopt/stop, queues, and live process discovery:
  outside foamlib's scope; OFTI owns this layer.
- OpenFOAM utilities without foamlib equivalents (`checkMesh`, `postProcess`
  custom functions, `yPlus`, `foamToVTK`, live solver process control) still need
  trusted subprocess execution.
- Boundary-condition semantic validation and numerics linting: foamlib supplies
  data access, but OFTI must own CFD-specific rules.
- Cross-fork syntax validation across OpenFOAM variants remains a slow real-case
  test responsibility.

## P1 follow-ups

- Re-check foamlib releases for a mesh stats API and replace `checkMesh` parsing
  where a reliable read-only API appears.
- Expand real-case tests for field IO round trips in non-trivial time directories.
- Keep direct upstream `foamlib` imports confined to `ofti/foamlib/*`.

# Foamlib Survey (checked against installed 1.5.5)

Foamlib is installed in `.venv` (version 1.5.5). The notes below are based on
local introspection of the package and the current OFTI adapter.

## Core API (foamlib 1.5.5)

- `FoamFile(path)`: read/write OpenFOAM dictionaries with dict-like access.
- `FoamFieldFile(path)`: field file support with `dimensions`, `internal_field`,
  `boundary_field`.
- `FoamCase(path)`: case helper with convenience properties and actions:
  `control_dict`, `fv_schemes`, `fv_solution`, `transport_properties`,
  `turbulence_properties`, `block_mesh_dict`, `decompose_par_dict`, `application`,
  plus actions: `run`, `block_mesh`, `decompose_par`, `reconstruct_par`, `clean`,
  `clone`, `restore_0_dir`.
- Dimension helpers: `DimensionSet`, `Dimensioned`.

## Currently used via `ofti/foamlib_adapter.py`

- Parse dictionary files (detect `FoamFile` header).
- `list_keywords(file)`: top-level keys.
- `list_subkeys(file, entry)`: nested keys.
- `read_entry(file, key)`: return raw/dumped text.
- `write_entry(file, key, value)`: scalar + uniform vector writes.
- `parse_boundary_file(path)`: read patch names + types from polyMesh/boundary.

## Direct integrations already in OFTI

- `ofti/foam/openfoam.py`: uses foamlib for read/write/list when available.
- `ofti/core/boundary.py`: uses foamlib for boundary file parsing.
- `ofti/ui_curses/blockmesh_helper.py`: uses foamlib to read vertices/blocks when available.
- Entry type detection (`ofti/core/entry_meta.py`) and syntax check flows prefer foamlib.

## Confirmed extras (from introspection)

- `FoamCase.run()` can execute a case end-to-end using heuristics:
  `Allrun`/`run` scripts, `blockMesh`, `restore_0_dir`, `decompose_par`, solver run,
  with optional parallel detection and `log.*` handling.
- `FoamCase.clean()` can clean logs/time/processor/mesh using heuristics or `Allclean`.
- `FoamCase.TimeDirectory` exposes `cell_centers()` helper (reconstructed cases).

## Still to verify/extend

- Field IO coverage for time directories (read/write boundary + internal values).
- Dictionary AST/formatting guarantees for round-trip stability.
- Mesh stats (cells/faces/points) extraction without `checkMesh`.
- Behavior across OpenFOAM forks / versioned syntax.

## P1 follow-ups once foamlib is installed

- Verify supported file types and error modes.
- Update adapter if foamlib offers richer type info for editors.
- Replace remaining shell tool usage for read-only inspections.

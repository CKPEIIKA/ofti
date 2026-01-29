# Foamlib adoption checklist (simple path)

Keep the integration lightweight and avoid duplicating OpenFOAM tooling:

- Prefer `foamlib` for *read/write* of dictionaries and fields.
- Keep shell tools only for “run” steps (solver, decompose, clean).
- Centralize file IO behind `core/entry_io.py` so UI never touches files directly.
- Avoid new parsing helpers unless foamlib cannot represent the data.
- Make tests rely on fixtures + foamlib instead of OpenFOAM binaries.

Short-term cleanup candidates:

- Retire custom boundary parsing where foamlib already covers it.
- Remove legacy parsing fallbacks unless they are trivial (<20 LOC).
- Keep adapters thin: no “manager” classes or deep wrappers.

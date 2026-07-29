# Real OpenFOAM Coverage Map

OFTI keeps unit tests for parsing and edge cases, but critical case-mutating
behavior should also have opt-in real OpenFOAM coverage. Real tests must use the
system-agnostic toy-case/profile adapters in `tests/real_openfoam_tutorials.py`
and `tests/real_openfoam_support.py`; they must not depend on local absolute
paths or host-specific scripts.

Run the slow suite explicitly:

```bash
source /usr/lib/openfoam/openfoam2512/etc/bashrc
OFTI_ENABLE_REAL_CASE_TESTS=1 uv run pytest --runslow tests/test_real_openfoam_toy_case.py
```

The real-toy module collects 30 service tests for the default cavity profile;
the generated/external profile module adds 16 reusable profile tests.
Current coverage proves that a manifest-restored case executes its solver,
that the public CLI can start, list, and stop a tracked real solver, and that
real OpenFOAM binary scalar/vector fields remain readable before and after
two-way decomposition. These paths pass with OpenFOAM 2512 sourced; the
queue/runtime/parallel-prepare subset also passes.
The generated-profile matrix reports `11 passed, 4 skipped`; three skips are
host-capability paths (MPI/foamlib parallel execution) and one is optional HPC.
(MPI launcher present but unusable in the sandbox network namespace).

The 2026-07-29 focused acceptance run against sourced OpenFOAM 2512 passed:

- an atomic multi-dictionary edit followed by a real two-step solver smoke;
- live run-state observation plus pause/resume;
- three-rank decomposition, latest-common restart planning, partial-time
  detection, and quarantine;
- a real two-rank exact smoke with readable rank output and successful
  `reconstructPar`;
- a full 2-to-3-rank stop, reconstruction, partial-time preservation,
  redecomposition, restart, and final stop.

MPI scenarios need local launcher sockets and therefore run outside restrictive
network sandboxes; a sandbox skip is capability evidence, not a passing test.

Optional knobs:

- `OFTI_REAL_CASES=icoFoam-cavity|simpleFoam-pitzDaily|interFoam-damBreak|all`
- `OFTI_TOY_CASE_TEMPLATE=/path/to/case`
- `OFTI_REAL_CASE_ROOT=/path/to/tutorial/root`
- `OFTI_REAL_PROFILES=caseA=/path/to/case;solver=simpleFoam;tags=serial`
- `OFTI_REAL_SCENARIOS=smoke,queue,parallel`

## Critical Service Matrix

| Service / behavior | Unit coverage | Toy real coverage | External profile coverage | Next gap |
| --- | --- | --- | --- | --- |
| Preflight / initials / physical scan | yes | yes | planned | Add more solver families via `OFTI_REAL_CASES=all`. |
| Run manifest write / verify / restore | yes | yes | planned | Toy path restores recorded inputs and executes the solver from the restored case. |
| Solver start / tracked status / stop | yes | yes | yes | Service and public CLI lifecycle are real-tested; MPI normalization runs when the launcher probe succeeds. |
| Exact smoke / clean exit / readable checkpoint / reconstruction | yes | yes | conditional | Real serial and two-rank runs prove all acceptance evidence; MPI needs a working launcher. |
| Parallel prepare / decompose | yes | yes | planned | Add reconstruct/decompose latest-time restart proof. |
| Restart planner / parallel resize-resume | yes | yes | yes | Real 2->3 flow proves common-time selection, partial preservation, reconstruct, redecompose, restart, and stop. |
| Queue execution and final status | yes | yes | yes | Real solver logs cover success, crash continuation/cleanup, and explicit criterion classification. |
| Runtime control / writeNow | yes | yes | planned | Toy path applies snapshot-protected `stopAt writeNow`; if the solver does not honor it live, the test verifies explicit stop fallback. |
| Bundle create / extract | yes | yes | planned | Real cases cover explicit external provenance embedding; add remote host-transfer smoke when a target exists. |
| Bundle-set restore / run | yes | yes | planned | Two independently hashed real cases are restored and both complete exact smoke runs. |
| Field compare / physical rules / metric reductions | yes | yes | yes | Generated profiles compare serial/decomposed fields; cavity covers binary internal reductions and a real patch value. |
| Checkpoint completeness | yes | yes | yes | Real decomposition proves complete reporting and partial-time quarantine without deletion. |
| Result pack / unpack | yes | yes | planned | Real solver output is packed, hash-verified, and restored. |
| Transactional dictionary edits | yes | yes | planned | Real text-preserving controlDict transaction is followed by a successful readable solver smoke. |
| Foamlib dictionary round trip | yes | yes | yes | A real controlDict is written/read through the adapter and the resulting case completes an exact smoke run. |
| Adopt / detached launcher discovery | yes | yes | conditional | Raw mpirun grouping/stop runs when the MPI launcher probe succeeds. |

## Policy

- If a test mutates or runs an OpenFOAM case, prefer a slow real-case test for
  the core service and keep only parser/error-path edges as unit tests.
- UI adapter tests should not launch OpenFOAM; they should assert wiring to the
  shared service.
- Skips must explain the missing command/profile so a developer can enable the
  real path deliberately.

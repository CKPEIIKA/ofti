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

Last local real-toy run with OpenFOAM 2512 sourced: `18 passed, 3 skipped`.
The generated-profile matrix reports `11 passed, 4 skipped`; three skips are
host-capability paths (MPI/foamlib parallel execution) and one is optional HPC.
(MPI launcher present but unusable in the sandbox network namespace).

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
| Run manifest write / verify / restore | yes | yes | planned | Toy path restores recorded inputs into a new case and verifies status/preflight. |
| Solver start / tracked status / stop | yes | yes | yes | MPI launcher/rank normalization is exercised when the launcher probe succeeds. |
| Parallel prepare / decompose | yes | yes | planned | Add reconstruct/decompose latest-time restart proof. |
| Parallel resize/resume | yes | yes | yes | Generated profile proves stopped 2->3 resize; live MPI restart remains launcher-dependent. |
| Queue execution and final status | yes | yes | yes | Real solver logs cover success, crash continuation/cleanup, and explicit criterion classification. |
| Runtime control / writeNow | yes | yes | planned | Toy path applies snapshot-protected `stopAt writeNow`; if the solver does not honor it live, the test verifies explicit stop fallback. |
| Bundle / unbundle | yes | yes | planned | Add external-profile host-transfer smoke once real remote profiles exist; CLI now reports target requirements. |
| Field compare / physical rules | yes | yes | yes | Generated profiles compare serial fields directly against decomposed fields with mesh identity. |
| Checkpoint completeness | yes | yes | yes | Real decomposition proves complete reporting and partial-time quarantine without deletion. |
| Result pack / unpack | yes | yes | planned | Real solver output is packed, hash-verified, and restored. |
| Transactional dictionary edits | yes | yes | planned | Real controlDict multi-edit uses one snapshot and all-or-rollback service. |
| Adopt / detached launcher discovery | yes | yes | conditional | Raw mpirun grouping/stop runs when the MPI launcher probe succeeds. |

## Policy

- If a test mutates or runs an OpenFOAM case, prefer a slow real-case test for
  the core service and keep only parser/error-path edges as unit tests.
- UI adapter tests should not launch OpenFOAM; they should assert wiring to the
  shared service.
- Skips must explain the missing command/profile so a developer can enable the
  real path deliberately.

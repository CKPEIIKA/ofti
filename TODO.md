# TODO

Unfinished work only. Completed work belongs in `DONE.md`.

## Runtime validation

- [ ] Parallel prepare/resize must keep geometric decompositions consistent: when `method` is `simple` or `hierarchical`, rewriting `numberOfSubdomains` alone leaves `n (a b c)` with a different product and decomposePar fails (reproduced by the opt-in real tests on OpenFOAM v2206, whose cavity tutorial ships `hierarchical` `n (3 3 1)`).
- [ ] Add result-pack remote-transfer smoke coverage when a portable target host is available.

## Deferred quality work

- [ ] Remove the global `PLR0913` ignore from the remaining 98 UI, dependency-injection, process-inspection, and fixture signatures where a typed request record has a clear contract.
- [ ] Remove the global `TRY003` ignore by moving repeated contextual messages into domain exception classes.
- [ ] Add a disposable Linux/native hy2Foam integration lane for parallel sampling, exact-step smoke, decomposed binary fields, and installable plugins.

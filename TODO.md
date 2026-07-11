# TODO

Unfinished work only. Completed work belongs in `DONE.md`.

## Quality debt

- [ ] Restore full-project 85% coverage after including `ofti/app/screens/` and `ofti/ui_curses/`; add behavior-focused coverage rather than new omit rules.
- [ ] Reduce the broad `ofti/app/**/*.py` complexity exception to explicit adapter files.
- [ ] Continue splitting broad watch and tool-screen tests so PLR0915 exceptions can be removed.

## Runtime validation

- [ ] Add result-pack remote-transfer smoke coverage when a portable target host is available.
- [ ] Run launcher/rank adoption and live resize/restart scenarios where MPI is permitted.

## Later

- [ ] Prototype a scheduler-neutral JSON adapter before adding SLURM-specific core behavior.
- [ ] Consider bundle-set only after single-case bundle and result-pack workflows are routine.
- [ ] Add plugin hooks only for demonstrated consumers.

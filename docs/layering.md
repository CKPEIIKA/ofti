# Layering and simplicity rules

This project keeps a very small set of layers to stay maintainable:

1. core
   - Pure logic only: parsers, helpers, data models.
   - No curses or UI imports.
   - No shelling out to OpenFOAM tools.

2. foam
   - OpenFOAM environment discovery and subprocess wrappers.
   - May depend on core, but must not depend on ui or ui_curses.

3. ui
   - Thin screen router and adapter interfaces.
   - Must not import ui_curses.

4. ui_curses
   - Curses screens and widgets.
   - Calls into core/foam via small helpers.

Rules of thumb:

- Add a new module only if it is reused in 2+ places.
- Avoid "manager" classes; prefer small functions.
- Keep UI code dumb: it should format and display data, not parse OpenFOAM files.

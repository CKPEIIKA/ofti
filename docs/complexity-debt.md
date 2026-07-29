# Complexity debt

The project limit is McCabe complexity 7, at most 7 branches, and at most 36
statements. Per-file ignores are a ratchet for legacy code, not a design target.
This inventory was generated with Ruff 0.16.0 using the configured limits on
2026-07-29.

## Highest remaining targets

| Rank | File and function | Rule/value | Responsibility groups to separate |
| ---: | --- | --- | --- |
| 1 | `ofti/app/cli_adapters/knife_parser.py::_build_knife_parser` | `PLR0915=324` | parser groups, argument families, plugin registration |
| 2 | `ofti/app/commands.py::handle_command` | `C901=33`, `PLR0912=32`, `PLR0915=67` | token decoding, command lookup, dispatch, error rendering |
| 3 | `ofti/ui_curses/entry_browser.py::entry_browser_screen` | `C901=30`, `PLR0912=33`, `PLR0915=98` | key decoding, navigation state, rendering, editor transitions |
| 4 | `ofti/app/helpers.py::select_case_directory` | `C901=29`, `PLR0912=28`, `PLR0915=99` | path policy, directory listing, selection state, rendering |
| 5 | `ofti/app/menus/simulation.py::simulation_menu` | `C901=29`, `PLR0912=28`, `PLR0915=66` | menu model, action dispatch, availability checks |
| 6 | `ofti/app/tool_screens/pipeline.py::pipeline_editor_screen` | `C901=28`, `PLR0912=30`, `PLR0915=88` | pipeline state, key handling, validation, rendering |
| 7 | `ofti/app/cli_adapters/run.py::_build_run_parser` | `PLR0915=143` | solver, smoke, queue, matrix, and resize parser builders |
| 8 | `ofti/app/cli_adapters/watch.py::_build_watch_parser` | `PLR0915=136` | job, log, attach, and process-control parser builders |
| 9 | `ofti/ui_curses/menus.py::display` | `C901=24`, `PLR0912=26`, `PLR0915=74` | viewport calculation, drawing, input, state updates |
| 10 | `ofti/app/screens/search.py::_collect_search_keys_text` | `C901=22`, `PLR0912=18`, `PLR0915=67` | source collection, filtering, formatting |

## Removed in this pass

| File and function | Before | After | Change |
| --- | --- | --- | --- |
| `ofti/app/clean_menu.py::clean_case_menu` | `C901=9`, `PLR0912=8` | no violation | separated menu loop from indexed action dispatch |
| `ofti/app/tasks.py::recent_task_summary` | `C901=8` | no violation | separated eligible-task selection from summary formatting |
| `ofti/app/cli_adapters/command_builder.py::_option_kwargs` | `C901=8` | no violation | split option identity and value mapping |

The three corresponding per-file exemptions were removed. No threshold or
blanket ignore was added.

The restart-plan parser/renderer was also moved into the cohesive
`run_restart.py` adapter, keeping `run.py` below the 1000-SLOC architecture
ratchet without adding an exemption. The remaining `_build_run_parser`
statement count is reported above rather than hidden.

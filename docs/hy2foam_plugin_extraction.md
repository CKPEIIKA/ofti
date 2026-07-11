# hy2Foam plugin extraction plan

## Context

OFTI is in reasonable architectural shape, but it is not yet cleanly generic
OpenFOAM software. The weak point is domain leakage: hy2Foam and air-chemistry
assumptions are currently visible inside generic diagnostics and CLI choices.

This plan is based on a static architecture review of `main`. It does not assume
that all behavior has been validated by the full test suite.

The command name remains `physical`; do not expose `nonphysical` as the primary
interface.

## Verdict

OFTI has a good base architecture:

- CLI adapters, tools/services, core modules, and foamlib integration are already
  conceptually separated.
- Architecture-boundary tests already prevent common layering violations such as
  library modules importing UI code, upstream foamlib imports leaking broadly,
  and library code importing CLI adapters.
- No rewrite is needed.

The main architectural debt is `ofti.core.field_diagnostics`: it mixes generic
field mechanics with hy2Foam/air-chemistry domain knowledge such as `air5`,
`air11`, charged species, modal temperatures, and species-sum semantics.

The target direction is strict:

```text
core owns mechanics; plugins own physics profiles
```

## Main problems for generic OpenFOAM usefulness

1. Core field presets are not generic.

   `air5`, `air11`, charged species, `e-`, `Tt`, and `Tv` are model-family
   conventions. Generic `flow` should be minimal, for example `p`, `U`, `rho`,
   and optionally `T` when present.

2. Physical diagnostics are hardcoded rather than rule-driven.

   Generic core should not know that `N2+`, `O2+`, `NO+`, or `e-` are species.
   It should only apply explicit rules such as `field rho must be finite and
   min >= 0`.

3. Species-sum checking is embedded in the generic payload.

   Sum(Y)=1 is not universally valid for every OpenFOAM case. It belongs in a
   profile/plugin, and it should only run when a complete species set is known.

4. CLI presets are currently plugin-shaped but hardcoded.

   `compare-fields --preset` should accept a string, resolve it through a
   registry, and print available presets on error. Argparse should not hardcode
   plugin preset names.

5. `knife physical` needs explicit CI semantics.

   Report-only mode may return `0` with `physical_ok=false`, but
   `--fail-on-bad` must return `1` when `physical_ok` is false. Invalid profile
   or preset names should return `2`.

6. `knife_service.py` is large and central.

   The extraction must not add plugin logic there. It should pass
   registry-selected presets/rules into core services.

7. Main README should lead with generic OpenFOAM examples.

   hy2Foam examples belong in an `ofti-hy2foam` README or a plugin-specific doc.

## Ownership split

| Area | Current examples | Target owner | Reason |
| --- | --- | --- | --- |
| Generic field scanning | finite checks, min/max/count, latest time, uniform/nonuniform parsing | OFTI core/service | Useful for all OpenFOAM solvers. |
| Generic field comparison | serial vs reconstructed parallel, model A/B comparisons | OFTI core/service | Solver-independent numeric comparison. |
| Generic physical rules | `--field rho:min=0`, `--field T:min=0`, `--fail-on-bad` | OFTI core/service | Rule engine is generic; plugins can add defaults. |
| Generic case execution/reporting | run, queue, manifests, log watching, convergence, reports | OFTI core/service | Generic OpenFOAM workflow. |
| Generic high-speed helper | Mach/static-to-total-pressure helper | OFTI core | Compressible-flow helper, not hy2Foam-specific. |
| Field preset registry | `flow`, plugin-provided presets | OFTI core registry | Registration/resolution is generic. |
| Command presets | `ofti.tools`, `ofti.postprocessing` | `ofti.core.tool_presets` | Do not overload this with field presets. |
| Air-chemistry presets | `air5`, `air11` | `ofti-hy2foam` plugin | Model-family defaults. |
| Species semantics | species sum, charged species, ions/electron | `ofti-hy2foam` plugin | Domain-specific physics assumptions. |
| hy2Foam solver defaults | `hy2Foam`, modal temperatures, multi-temperature assumptions | `ofti-hy2foam` plugin | Solver-specific conventions. |
| Charge observability | electron density, ion charge density, wall BC charge listing | `ofti-hy2foam` plugin | Useful but not generic. |
| hy2Foam real tests | hy2Foam tutorials/lab cases | plugin test package | Generic slow tests should use canonical OpenFOAM cases. |
| TUI labels/cards | hy2Foam-aware hints | TUI plugin adapter | Presentation only; call plugin services. |

## Refactor target

```text
ofti/core/field_io.py
  FieldData, read_internal_field, uniform/nonuniform parsing, numeric coercion,
  latest-time hooks.

ofti/core/field_stats.py
  field summaries, finite counts, min/max, component counts, scalar/vector
  handling.

ofti/core/field_compare.py
  case A/B comparison, serial/reconstructed comparison, component/count mismatch,
  tolerances.

ofti/core/physical_rules.py
  FieldRule, rule parsing, rule application, violation records, physical_ok.

ofti/core/field_presets.py
  generic preset registration and resolution. Built-ins stay minimal and
  solver-independent.

ofti/plugins.py or ofti/plugins/registry.py
  entry-point discovery and provider registration.

ofti_hy2foam/
  hy2Foam presets, physical profile, species rules, charge command, slow real
  hy2Foam tests.
```

Core must never import `ofti_hy2foam`. The plugin imports OFTI interfaces.

## Provider API sketch

Keep the provider API smaller than plugin internals.

```python
from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Protocol, Sequence


@dataclass(frozen=True)
class FieldPreset:
    name: str
    fields: tuple[str, ...]
    description: str = ""
    source: str = "core"


@dataclass(frozen=True)
class FieldRule:
    field: str
    min_value: float | None = None
    max_value: float | None = None
    required: bool = False
    description: str = ""


@dataclass(frozen=True)
class ProfileMatch:
    confidence: float
    reasons: tuple[str, ...] = ()


class FieldPresetProvider(Protocol):
    def presets(self) -> Sequence[FieldPreset]: ...


class PhysicalRuleProvider(Protocol):
    name: str

    def detect(self, case_dir: Path) -> ProfileMatch: ...

    def fields(self, case_dir: Path) -> Sequence[str]: ...

    def rules(self, case_dir: Path) -> Sequence[FieldRule]: ...


class KnifeCommandProvider(Protocol):
    name: str

    def add_parser(self, subparsers) -> None: ...

    def run(self, args) -> int: ...


@dataclass
class PluginRegistry:
    presets: dict[str, FieldPreset] = field(default_factory=dict)
    physical_profiles: dict[str, PhysicalRuleProvider] = field(default_factory=dict)
    knife_commands: dict[str, KnifeCommandProvider] = field(default_factory=dict)
```

Discovery should use Python entry points:

```python
def discover_plugins() -> PluginRegistry:
    registry = builtin_registry()

    for ep in entry_points(group="ofti.plugins"):
        register = ep.load()
        register(registry)

    return registry
```

## CLI target

Keep the public command name `physical`.

```text
ofti knife physical CASE
ofti knife physical CASE --field rho:min=0 --field p:min=0
ofti knife physical CASE --fields p,U,rho --fail-on-bad
ofti knife physical CASE --profile hy2foam --fail-on-bad
ofti knife physical CASE --profile hy2foam --json
```

Semantics:

- `--fields` selects fields to scan/report.
- `--field` adds an enforced rule.
- `--profile hy2foam` asks the plugin registry for default fields and rules.
- `--fail-on-bad` returns `1` when `physical_ok` is false.
- Missing profile returns `2` with a direct error:
  `ofti: physical profile 'hy2foam' is not available; install ofti-hy2foam`.

For comparison, remove hardcoded argparse choices:

```text
ofti knife compare-fields CASE --against OTHER --preset flow
ofti knife compare-fields CASE --against OTHER --preset air11
```

`flow` works from core. `air11` works only if `ofti-hy2foam` is installed.
Without the plugin, return `2` with an available-preset list.

## `ofti-hy2foam` package shape

```text
ofti-hy2foam/
  pyproject.toml
  src/ofti_hy2foam/__init__.py
  src/ofti_hy2foam/plugin.py
  src/ofti_hy2foam/presets.py
  src/ofti_hy2foam/physical.py
  src/ofti_hy2foam/charge.py
  tests/
    test_plugin_registration.py
    test_hy2foam_presets.py
    test_hy2foam_physical_profile.py
    test_charge_command.py
    test_real_profiles.py
```

Entry point:

```toml
[project.entry-points."ofti.plugins"]
hy2foam = "ofti_hy2foam.plugin:register"
```

Registration:

```python
from ofti.plugins import FieldPreset, PluginRegistry
from .charge import Hy2FoamChargeCommand
from .physical import Hy2FoamPhysicalProfile


def register(registry: PluginRegistry) -> None:
    registry.presets["air5"] = FieldPreset(
        name="air5",
        fields=("N2", "O2", "NO", "N", "O"),
        description="hy2Foam five-species air model",
        source="ofti-hy2foam",
    )
    registry.presets["air11"] = FieldPreset(
        name="air11",
        fields=("N2", "O2", "NO", "N", "O", "N2+", "O2+", "NO+", "N+", "O+", "e-"),
        description="hy2Foam ionized eleven-species air model",
        source="ofti-hy2foam",
    )
    registry.physical_profiles["hy2foam"] = Hy2FoamPhysicalProfile()
    registry.knife_commands["charge"] = Hy2FoamChargeCommand()
```

Consider namespacing the charge command as `hy2foam-charge` or
`hy2foam charge` to avoid future collisions. If the exact command
`ofti knife charge` is used, the registry must reject duplicate plugin command
names deterministically.

## Physical-rule model

Core applies rules. It does not invent domain rules.

Generic examples:

```python
FieldRule("rho", min_value=0.0)
FieldRule("p", min_value=0.0)
FieldRule("T", min_value=0.0)
FieldRule("alpha.water", min_value=0.0, max_value=1.0)
```

hy2Foam plugin examples:

```python
FieldRule("rho", min_value=0.0)
FieldRule("p", min_value=0.0)
FieldRule("T", min_value=0.0)
FieldRule("Tt", min_value=0.0)
FieldRule("Tv", min_value=0.0)
FieldRule("N2", min_value=0.0, max_value=1.0)
FieldRule("O2", min_value=0.0, max_value=1.0)
```

Species-sum is a plugin diagnostic, not a normal `FieldRule`, because it is a
multi-field invariant. It should be optional unless the plugin can confirm the
case uses a complete mass-fraction set.

Recommended JSON shape:

```json
{
  "ok": true,
  "physical_ok": false,
  "profile": "hy2foam",
  "time": "latest",
  "fields": [],
  "violations": [],
  "diagnostics": {
    "species_sum": {
      "checked": true,
      "max_abs_deviation": 0.03,
      "tolerance": 1e-8
    }
  }
}
```

Stable keys should exist even when a diagnostic is not run:

```json
"species_sum": {
  "checked": false,
  "reason": "profile not selected"
}
```

## Migration order

1. Add the registry and generic preset module. Keep old `FIELD_PRESETS` as a
   compatibility wrapper, but make it delegate to `field_presets.builtin_registry()`.
   Move only `flow` into core.
2. Split `field_diagnostics.py`. Preserve existing public function names by
   re-exporting wrappers while `knife_service.py` migrates.
3. Introduce generic physical rules. Add `--field` and `--fail-on-bad`. Keep
   `--fields` compatibility. Do not add `--profile` yet.
4. Remove hardcoded `air5` and `air11` from core and CLI. Change
   `compare-fields --preset` from fixed argparse choices to registry validation.
5. Create `ofti-hy2foam` with `air5`, `air11`, `hy2foam` profile, species-sum
   diagnostic, and charge command.
6. Add `--profile hy2foam`. If the plugin is absent, return code `2` with a
   clear missing-plugin error.
7. Move real hy2Foam tests into the plugin. Generic OFTI slow tests should use
   canonical OpenFOAM tutorials or synthetic fields.
8. Update README. Main README should show generic OpenFOAM examples. hy2Foam
   examples move to the plugin README.

## Architecture tests to add

Add a domain-boundary test in addition to the existing UI/CLI/foamlib boundary
checks.

```python
DOMAIN_FORBIDDEN = {
    "hy2Foam",
    "air5",
    "air11",
    "N2+",
    "O2+",
    "NO+",
    "electron",
    "ion",
    "e-",
}

CHECK_PATHS = [
    Path("ofti/core"),
    Path("ofti/tools"),
]
```

Expected behavior:

```python
def test_core_and_tools_do_not_hardcode_hy2foam_terms(repo_root: Path) -> None:
    offenders = []

    for base in CHECK_PATHS:
        for path in (repo_root / base).rglob("*.py"):
            rel = path.relative_to(repo_root)
            if rel in ALLOWLIST:
                continue

            text = path.read_text(encoding="utf-8")
            for term in DOMAIN_FORBIDDEN:
                if term in text:
                    offenders.append(f"{rel}: {term}")

    assert not offenders
```

Also add CLI tests:

```text
ofti knife physical CASE --field rho:min=0
  works with no plugins

ofti knife physical CASE --profile hy2foam
  returns 2 when plugin is missing

ofti knife physical CASE --profile hy2foam
  works when fake plugin is registered

ofti knife compare-fields CASE --against OTHER --preset air11
  returns 2 without plugin

ofti knife compare-fields CASE --against OTHER --preset air11
  resolves through plugin when installed
```

Exit-code tests:

```text
physical violation + no --fail-on-bad -> exit 0, physical_ok false
physical violation + --fail-on-bad -> exit 1
parse error / unknown profile / unknown preset -> exit 2
nonfinite hard field read error -> exit 1
```

## Main vs tui-overhaul audit

The cherry-pick rule is:

- generic case fingerprinting, plotting primitives, and latest-time helpers are
  main-worthy;
- Captains Deck, mesh radar, monitor builder, flight deck services, and
  Textual/curses layout work stay on `tui-overhaul` until there is a core or CLI
  consumer.

If public `main` still differs from local `main`, do not treat audit text as a
substitute for a merge. Keep the branch split explicit: non-TUI reusable code can
move to `main`; TUI product surfaces stay on `tui-overhaul`.

## Acceptance criteria

```text
rg "hy2Foam|air5|air11|N2\\+|O2\\+|NO\\+|electron|e-|ion" ofti/core ofti/tools
```

should return nothing except explicit plugin-registry error messages or tests
that enforce absence.

Additional required behavior:

- `ofti knife physical CASE --field rho:min=0 --fail-on-bad` returns `1` when
  `rho` is negative.
- `ofti knife compare-fields CASE --against OTHER --preset air11` returns `2`
  unless `ofti-hy2foam` is installed.
- Main README does not use hy2Foam as the default introductory solver.
- hy2Foam documentation lives in `ofti-hy2foam` docs.
- Generic OFTI slow tests use canonical OpenFOAM cases or synthetic fields.

## What can be done right now

Immediate low-risk steps in `main`:

1. Add `ofti/core/field_presets.py` with only generic built-ins.
2. Change `compare-fields --preset` from argparse choices to runtime registry
   validation.
3. Make `physical --fail-on-bad` return `1` on `physical_ok=false` and add tests.
4. Add `--profile` plumbing that returns `2` for unavailable profiles before any
   real plugin exists.
5. Add domain-boundary tests with an allowlist for the current migration state,
   then shrink the allowlist as `field_diagnostics.py` is split.

Next bigger slice:

1. Split `field_diagnostics.py` into field IO, stats, compare, and physical-rule
   modules while preserving compatibility imports.
2. Remove air-chemistry defaults from core.
3. Create a separate `ofti-hy2foam` package skeleton with plugin registration,
   presets, physical profile, and tests.

## hy2Foam plugin backlog details

These are intentionally plugin tasks, not OFTI-core tasks.

### hy2Foam physical diagnostics

`ofti knife physical` stays generic. The hy2Foam plugin should provide a
hy2Foam-aware profile that checks:

- `Tt`, `Tv`, `Tov`, `p`, `rho`, `e`, `ev`;
- species bounds and complete `sum(Y_i)` when the species set is known;
- negative/NaN `Dmix`, `rhoD`, `J`, `qDiff`, and `wallHeatFlux`;
- 2T sanity such as unreasonable `Tv/Tt` relation;
- patch ranges, especially wall and stagnation-layer fields.

### Charge / ionization diagnostics

Add `ofti knife charge` or a namespaced plugin command. It should report:

- electron number density from `rho * Y_e / m_e`;
- positive-ion charge number density;
- net charge imbalance;
- charged-species wall boundary-condition audit;
- warning when charged species exist but ambipolar/neutrality treatment is not
  configured.

This must stay observational; it must not imply that OFTI fixes plasma physics.

### hy2Foam preflight

Generic preflight is not enough for hy2Foam. The plugin preflight should check:

- OpenFOAM version profile, initially v2512;
- required hyStrath libraries;
- `Tt`, `Tv`, `p`, `U`, and species fields against mesh patches;
- species order consistency across thermo, chemistry, transport, and NN
  input/output order;
- turbulence/laminar consistency;
- duplicate functionObjects;
- invalid NNcompiled headers/config, missing `precompiledModel`, wrong
  `stateInputOrder`.

### Hypersonic convergence criteria

Add case-aware criteria for:

- shock stand-off stationarity;
- stagnation pressure and heat-flux stability;
- mass balance stability;
- atomic/element balance stability;
- `sumJ` near zero for corrected Fick models;
- wall heat-flux stability over a window;
- ignoring misleading wall criteria when non-informative.

### hy2Foam compare presets

Provide richer plugin presets beyond generic `flow`:

- `transport`: `Dmix_*`, `rhoD_*`, `J_*`, `sumJ`, `qDiff`;
- `2T`: `Tt`, `Tv`, `Tov`, modal energies;
- `wall`: `wallHeatFlux`, `qCond`, `qDiff`, pressure;
- patch compare support, not only internal fields;
- latest common time detection;
- same-mesh verification before cellwise comparison.

### Optional model-runtime inspection

NNcompiled-style diagnostics are fork/profile-specific, not a default hy2Foam
plugin requirement. If a fork declares a stable model-runtime contract, provide
a namespaced extension command that can report:

- active model identifier;
- input/output order, species basis, and output scaling;
- registry/config presence;
- optional dynamic-vs-compiled probe checks;
- runtime fraction per CFD step where logs expose it.

### hy2Foam plotting

Extend plotting in the plugin for:

- wall heat flux and wall pressure;
- stagnation-line profiles;
- `Dmix`, `J`, and `qDiff` profiles;
- field maps via ParaView where available;
- shock stand-off evolution;
- grid-convergence plots.

### hy2Foam run matrices

Add plugin matrix presets for:

- validation matrix: air5 diffusion, catalytic diffusion, cylinder;
- transport sweep: Fick, Lewis, SCEBD, Gupta, Wright, NN;
- grid convergence.

# Legacy Indicator Phase 4 Audit

## Outcome

Phase 4 makes the Pine v4 input system executable without changing modern
input rules. The legacy analyzer binds the historical overloaded `input()`
signatures, resolves version-gated type constants, removes the obsolete `type`
argument, and lowers the call to the existing canonical `input.*` runtime.

The supported v4 mappings are:

| Pine v4 type constant | Canonical call |
| --- | --- |
| `input.bool` | `input.bool` |
| `input.color` | `input.color` |
| `input.integer` | `input.int` |
| `input.float` | `input.float` |
| `input.string` | `input.string` |
| `input.symbol` | `input.symbol` |
| `input.resolution` | `input.timeframe` |
| `input.session` | `input.session` |
| `input.source` | `input.source` |
| `input.time` | `input.time` |
| `input.price` | `input.price` |

Omitted `type` values are inferred only for the fixture-backed int, float,
bool, string, color, and source forms. Pine v1-v3 inputs remain closed until
their version phases, and legacy strategies remain permanently out of scope.

## Historical Contract

The binder was derived from TradingView's archived
[Pine v4 input documentation](https://www.tradingview.com/pine-script-docs/v4/annotations/script-inputs/)
and [v4 reference](https://in.tradingview.com/pine-script-reference/v4/), then
cross-checked against the official
[v4-to-v5 migration guide](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/).
Those sources establish three important differences from current Pine:

1. one `input()` function selected several historical overloads through a
   `type` constant;
2. the parameter order varied by return family and did not match the later
   specialized functions;
3. `input.integer` became `input.int`, while `input.resolution` became
   `input.timeframe` and the other type names became corresponding functions.

The implemented positional tables are deliberately separate:

```text
bool/color/symbol/resolution/session/time/price
  defval, title, type, confirm, tooltip, inline, group

integer/float
  defval, title, type, minval, maxval, confirm, step, options,
  tooltip, inline, group

string
  defval, title, type, confirm, options, tooltip, inline, group

source
  defval, title, type, inline, group, tooltip
```

All retained arguments are converted to canonical named arguments before the
existing registry validates them. This is required because, for example,
v4 placed `confirm` before `step` and `options` for numeric inputs. The v4-only
integer compatibility view also accepts const-float `minval`, `maxval`, and
`step` metadata, matching the migration guide's documented old behavior. That
exception is parameter-specific; a modern `input.int(..., minval=1.0)` remains
an `E_CALL_ARG_TYPE` failure.

`display` is not accepted as a v4 name. `confirm` is rejected for the source
overload as required by the old contract. Options and numeric metadata are
limited to the documented fixture-backed overloads rather than being accepted
globally.

## Type Constants and Overload Safety

The old type constants are not added to the canonical built-in registry.
Instead, a v4-only focused value resolver records a `constantAlias`
translation and lowers the constant to an opaque internal string marker. The
input binder recognizes that marker only in its `type` slot.

This design has four consequences:

- a local const alias such as `kind = input.integer` can be passed to a later
  input call;
- an ordinary string such as `"input.int"` cannot impersonate a type constant;
- the marker cannot become a numeric value through global coercion;
- v5 and v6 still reject `input.integer` and the other removed constants.

An unresolved or forged type, an uninferable default value, or an otherwise
ambiguous overload emits `E_LEGACY_INPUT_OVERLOAD` before HIR or runtime.
Historical name, order, arity, and duplicate errors retain the original
`input` spelling and source spans.

## Lowering and Callsite Identity

The source-context/span lowering plan now stores an argument rewrite for every
legacy call argument:

```text
keep + canonical name
drop
```

`type` receives `drop`; every executable argument receives `keep` plus its
canonical name. The call expression itself is not synthesized or moved, so
callsite allocation remains in source traversal order. The paired fixture has
the same callsite ids `1..11`, input names, and titles as its canonical form.

Runtime execution continues through the existing `input.*` implementations.
CLI, WASM, and Python therefore consume canonical metadata and the existing
callsite-keyed override parsers. The established boundary remains unchanged:
scalar and string-like input overrides are supported, while host overrides for
`input.source` remain unsupported.

`LEGACY_TRANSLATOR_REVISION` is now `3`, preventing compile-cache reuse across
the new value and argument-rewrite semantics.

## Fixture Evidence

The primary pair is:

- `tests/fixtures/legacy/v4/runtime/inputs_legacy.pine`
- `tests/fixtures/legacy/v4/runtime/inputs_canonical.pine`

It covers all eleven explicit type constants, historical positional order,
numeric bounds/step/options, string options, confirmation and layout metadata,
source metadata ordering, qualifiers, titles, callsite ids, default execution,
and scalar host overrides. The normalized HIR programs are identical after
removing only the source language version.

`tests/fixtures/legacy/v4/sema/input_constant_alias.pine` separately proves a
local const alias of `input.integer`. Analyzer tests also cover inferred scalar
and source overloads, forged type strings, missing defaults, invalid source
confirmation, unique-value arithmetic rejection, the v4-only float-metadata
exception, and v5/v6 negative controls.

CLI JSON exposes the canonical input metadata and constant translation. WASM
and Python compile the v4 fixture and apply callsite-keyed overrides. A Rust
runtime test compares the complete default and overridden `RuntimeResult`
values against the canonical fixture.

## Corpus Effect

The unchanged 29-item Phase 0 manifest was run twice with fixed build revision
`phase4`. The reports were byte-for-byte identical with SHA-256:

```text
3c26a9695cf72c30cb564b4105f1eecae26ff78b62031b917090605b2e5372f8
```

Rates retain the denominator of 22 eligible legacy indicators:

| Stage | Passed | Attempted | Eligible denominator | Rate |
| --- | ---: | ---: | ---: | ---: |
| Parse | 22 | 22 | 22 | 100% |
| Analyze | 5 | 22 | 22 | 22.73% |
| Lower | 5 | 5 | 22 | 22.73% of eligible; 100% of attempted |
| Historical run | 5 | 5 | 22 | 22.73% of eligible; 100% of attempted |

Within v4, analyze and historical-run coverage increased from 4 of 12 to 5 of
12 indicators (41.67%). The newly passing item is
`legacy_v4_input_integer`. The v3 typed-input item remains behind the pre-v4
declaration gate and was not incorrectly attributed to this phase.

The leading remaining clusters are 10 pre-v4 declarations, five known
unsupported v4 features, two `plot.series` cascades, two unqualified `change`
calls, and the remaining single output/alias cases. Incremental, realtime, and
reference-output stages remain `notRun` in the corpus tool and are not counted
as passing.

## Deferred Boundary

- Unqualified v3 constants such as `integer` remain Phase 8 work.
- Primitive plot/hline styles and output transparency remain Phase 5 work.
- Legacy expression overloads, `iff`, `offset`, and session-day behavior remain
  Phase 6 work.
- `security`, declaration resolutions, and downstream use of resolution/session
  inputs remain Phase 7 work.
- Host-side source-input overrides remain outside the existing override
  contract.
- No legacy strategy analysis, lowering, runtime, or migration path is added.

## Verification

Targeted semantic, runtime, CLI, WASM, and installed-wheel Python tests passed.
The matrix snapshot was refreshed only through its documented
`UPDATE_SNAPSHOTS=1` workflow and then passed again without the update flag.
The complete `scripts/verify.sh` release gate passed after the legacy lowering
helpers were split out to keep `lowering/mod.rs` below the structural limit.
That gate included the Rust workspace and doc tests, all 511 WASM tests, all
485 installed-wheel Python tests, the 295-file structural guard, the nine
corpus-analyzer tests, host-parity checks, and the Node WASM smoke test.

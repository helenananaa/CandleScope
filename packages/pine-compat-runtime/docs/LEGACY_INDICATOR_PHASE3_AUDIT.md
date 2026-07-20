# Legacy Indicator Phase 3 Audit

## Outcome

Phase 3 opens the first production legacy execution slice: ordinary Pine v4
indicators declared with `study(...)` can analyze, lower, and run when they stay
inside the verified single-timeframe declaration subset and use the first
corpus-selected exact aliases.

The enabled aliases are deliberately small:

| v4 source | Canonical target | Selection evidence |
| --- | --- | --- |
| `sma` | `ta.sma` | frequent corpus cluster and unlocks the basic v4 fixture |
| `ema` | `ta.ema` | unlocks the stateful EMA-cross fixture |
| `bb` | `ta.bb` | unlocks the tuple-returning Bollinger fixture |
| `crossover` | `ta.crossover` | completes the EMA-cross fixture |
| `abs` | `math.abs` | unlocks the unqualified math fixture |

No v1-v3 declaration is admitted by this phase. Legacy strategies remain a
permanent out-of-scope hard stop.

## Background Audit

The declaration binder was derived from historical documentation rather than
from the current `indicator(...)` signature:

- the archived [Pine v4 reference manual](https://in.tradingview.com/pine-script-reference/v4/)
  lists `study(title, shorttitle, overlay, format, precision, scale,
  max_bars_back, max_lines_count, max_labels_count, resolution,
  resolution_gaps, max_boxes_count, explicit_plot_zorder)`;
- TradingView's official [v4-to-v5 migration guide](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/)
  identifies `study()` as the predecessor of `indicator()`, documents the
  namespace move for calls such as `sma()` to `ta.sma()`, and requires
  `resolution`/`resolution_gaps` to become `timeframe`/`timeframe_gaps`;
- the repository's canonical `INDICATOR_PARAMS` supports title metadata,
  overlay/format/precision/scale, `max_bars_back`, and current drawing-count
  limits, but it intentionally has no declaration-level timeframe execution
  contract yet.

The Phase 0 corpus also showed why a broad migration-table import would be the
wrong unit of work. A five-alias batch plus `study` unlocks four complete v4
indicators. Adding `change`, `max`, `min`, `highest`, or `lowest` in isolation
would translate more tokens but would not unlock their scripts because those
scripts still depend on Phase 6 expression/overload semantics.

## Declaration Translation

`legacy::declarations` owns a dedicated v4 signature table. Binding occurs in
this order:

1. validate v4 positional/named order, names, duplicates, arity, and required
   `title`;
2. bind against the historical parameter order;
3. convert every supported argument to its canonical named parameter;
4. validate the converted call against the existing `indicator` registry;
5. record `study -> indicator` as a `signatureReshape` translation;
6. lower only `indicator` plus canonical argument names into HIR.

Converting supported arguments to names is required because historical
`max_lines_count` and `max_labels_count` positions do not match the current
canonical drawing-count order. The lowering plan stores those names by source
context and callee span alongside the canonical function name, so the AST and
public source spans remain unchanged.

Supported declaration parameters in this phase are:

```text
title
shorttitle
overlay
format
precision
scale
max_bars_back
max_lines_count
max_labels_count
max_boxes_count
```

Any supplied `resolution` or `resolution_gaps` arguments are aggregated into
one `study.resolution` unsupported record and one error diagnostic. They do not
reach canonical validation or HIR. `explicit_plot_zorder` is also recognized
and rejected because the current indicator contract has no verified equivalent.

## Exact Alias Path

The five production aliases are v4-only `ExactFunctionAlias` catalog rows.
They retain the Phase 2 resolution order:

1. canonical built-in;
2. imported/local method paths;
3. user-defined function;
4. lexical call shadow check;
5. versioned legacy fallback.

Consequently a user function or lexical value named `sma` wins over the alias,
while v5/v6 `sma`, `ema`, `bb`, `crossover`, and `abs` remain unknown. Successful
legacy calls are reported with original source spans, but semantic validation,
tuple element typing, HIR, and runtime dispatch all consume canonical names.

The tuple element query required an explicit Phase 3 correction: after
`bb -> ta.bb` analysis, tuple destructuring now reads the same span-keyed
canonical name rather than independently re-resolving the original `bb` token.
This keeps the analyzer and lowerer on one translation decision.

`LEGACY_TRANSLATOR_REVISION` is now `2`, preventing compile-cache reuse across
the first production translation change.

## Fail-Closed Semantics

Opening the v4 declaration gate made canonical names with historical behavior
differences reachable. `time(timeframe, session)` is therefore guarded for
legacy dialects until Phase 6 implements the v4 session-day default. It reports
`time.session` as unsupported instead of silently running with modern weekday
semantics.

Legacy typed inputs, output styles/transparency, `iff`, `offset`, the v4 `rsi`
overload, `security`, and declaration timeframes remain owned by their planned
focused phases. Unknown aliases remain unknown; this phase does not add global
coercions or generic namespace fallback.

## Fixture and Host Evidence

The paired fixtures use identical expressions and bars:

- `tests/fixtures/legacy/v4/runtime/aliases_legacy.pine`
- `tests/fixtures/legacy/v4/runtime/aliases_canonical.pine`
- `tests/fixtures/legacy/v4/sema/declaration_legacy.pine`
- `tests/fixtures/legacy/v4/sema/declaration_canonical.pine`

They prove:

- normalized legacy/canonical HIR equality after excluding only the source
  language-version field;
- identical historical runtime results for all five aliases;
- historical positional declaration binding and current drawing settings;
- `max_bars_back`, `max_lines_count`, `max_labels_count`, and
  `max_boxes_count` metadata parity;
- one focused failure for both supplied timeframe arguments;
- user-function and lexical collision precedence;
- v5/v6 negative controls for every production alias;
- CLI, WASM, and Python projections of executable v4 translation records;
- conformance ownership for every production catalog row.

## Corpus Effect

The 29-item Phase 0 manifest was run twice with fixed build revision `phase3`.
The JSON reports were byte-for-byte identical; the SHA-256 digest was:

```text
b2d620bc184671be740b732253bccdc65129df9fbd03ecce1906044e8d65bbd4
```

Rates use the unchanged denominator of 22 eligible legacy indicators:

| Stage | Passed | Attempted | Eligible denominator | Rate |
| --- | ---: | ---: | ---: | ---: |
| Parse | 22 | 22 | 22 | 100% |
| Analyze | 4 | 22 | 22 | 18.18% |
| Lower | 4 | 4 | 22 | 18.18% of eligible; 100% of attempted |
| Historical run | 4 | 4 | 22 | 18.18% of eligible; 100% of attempted |

Within v4, 4 of 12 indicators analyze and run (33.33%). The passing fixtures
are Bollinger Bands, EMA cross, unqualified `abs`, and basic SMA. The remaining
top clusters are now actionable:

| Cluster | Count | Planned owner |
| --- | ---: | --- |
| pre-v4 declaration gate | 10 | Phases 8-9 |
| known unsupported v4 feature | 5 | Phases 6-7 |
| legacy `plot.series` cascade | 2 | Phase 5/upstream focused feature |
| unqualified `change` | 2 | Phase 6 |
| typed input names | 2 | Phase 4 |
| `plot.transp` | 1 | Phase 5 |
| primitive plot style | 1 | Phases 4-5 |

Incremental, realtime, and external reference-output stages remain `notRun` in
the current corpus tool; this phase does not misreport them as passing.

## Verification

The Phase 3 implementation passed the repository's complete release gate with
`scripts/verify.sh`. That gate covered formatting, all Rust workspace tests and
doc tests, the 1,500-line structural limit across 294 production Rust files,
the legacy-corpus analyzer's 9 unit tests, host-parity guards, the WASM Node
smoke suite, wheel construction and installation, and all 484 Python binding
tests. The conformance matrix snapshot was regenerated only through the
documented `UPDATE_SNAPSHOTS=1` test workflow and then passed again without the
update flag.

## Deferred Boundary

- v1-v3 `study` lowering remains closed.
- `study(resolution=...)` and `study(resolution_gaps=...)` remain closed until
  Phase 7.
- No legacy input overload or constant is implemented here.
- No legacy output option or transparency behavior is implemented here.
- No legacy expression, session, `security`, lookahead, self-reference, or
  conversion semantics are implemented here.
- No legacy strategy conversion or runtime path will be added.
- The public analysis schema remains version 4; Phase 3 populates the existing
  translation contract without a schema change.

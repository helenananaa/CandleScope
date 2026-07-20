# Legacy Indicator Phase 8 Audit

## Outcome

Phase 8 makes the fixture-backed Pine v3 indicator subset executable. It adds
the historical v3 `study`, `input`, `plot`, and `hline` call shapes; pre-v4
color, style, weekday, input-type, and chart-metadata names; the old
`color(base, transp)` helper; v3 admission for the already canonicalized
`ema`/`sma` family; and a narrow untyped-`na` inference rule.

All seven v3 indicators in the unchanged Phase 0 corpus now parse, analyze,
lower, and run. Pine v4 remains 12 of 12. The only three eligible failures are
the one v1 and two v2 declaration/semantic fixtures reserved for Phase 9.
Legacy strategies remain out of scope, and no v4-v6 declaration or namespace
rule is relaxed.

## Historical Background

The version boundary was checked against TradingView's official
[v3 release notes](https://www.tradingview.com/pine-script-docs/v3/release-notes/),
archived v3 documentation for
[`study`](https://www.tradingview.com/pine-script-docs/v3/annotations/study-annotation/),
[`input`](https://www.tradingview.com/pine-script-docs/v3/annotations/script-inputs/),
[`plot`](https://www.tradingview.com/pine-script-docs/v3/annotations/plot-annotation/),
and
[`hline`](https://www.tradingview.com/pine-script-docs/v3/annotations/price-levels-hline/),
plus the official
[v3-to-v4 migration guide](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-4/).

Those sources establish the Phase 8 boundaries:

- v3 `study` has `title`, `shorttitle`, `overlay`, and `precision`; later
  declaration parameters do not belong to this profile;
- keyword arguments are available in v3, so the binder accepts the historical
  positional/named forms but still rejects positional arguments after named
  ones;
- the v3 input families are bool, integer, float, string, symbol, resolution,
  session, and source, with type-specific historical parameter order;
- unqualified colors became `color.*`, the old `color(...)` helper became
  `color.new(...)`, and style/weekday constants moved into namespaces in v4;
- `period`, timeframe classification names, and `interval` became
  `timeframe.*`; `ticker`/`tickerid` became `syminfo.*`; and `n` became
  `bar_index`;
- v4 rejected declarations whose type could not be determined from an initial
  `na`, so v3 compatibility needs a version-scoped inference rule rather than
  a global weakening of declaration typing.

## Phase Plan And Decisions

The implementation used six gates:

1. verify v3 declaration, input, output, name, and typing boundaries;
2. extend the existing versioned catalog and binders instead of creating a
   parallel interpreter;
3. prove source-symbol precedence and modern negative controls;
4. infer only one fixture-proven scalar type for untyped `na` declarations;
5. prove canonical HIR and historical/incremental runtime equivalence;
6. synchronize conformance, hosts, corpus evidence, diagnostics, and release
   documentation before the phase commit.

The implementation deliberately does not rewrite source text. Resolution
records a source-context/span keyed decision, semantic analysis checks the
canonical target, and lowering emits canonical HIR. This preserves original
diagnostic spans while keeping the runtime free of source-version name tables.

Untyped `na` is also not treated as unconstrained dynamic typing. The accepted
form must receive one later scalar assignment. Unresolved declarations,
collection/object assignments, and later incompatible assignments fail before
HIR is produced. Consumer-only inference and arbitrary flow solving remain
outside the claimed subset.

## Versioned Declaration, Input, And Output Binding

`study` now has separate v3 and v4 parameter tables. The v3 table exposes only
the four historical parameters; `format` and other later arguments receive the
ordinary stable call diagnostics. v1/v2 declaration admission remains closed
for Phase 9.

The input binder selects a v3 table after resolving an explicit historical type
constant or, when omitted, the default-value type. Its accepted shapes are:

| Family | Historical v3 roles |
| --- | --- |
| bool/symbol/resolution/session | `defval`, `title`, `type`, `confirm` |
| integer/float | `defval`, `title`, `type`, `minval`, `maxval`, `confirm`, `step`, `options` |
| string | `defval`, `title`, `type`, `confirm`, `options` |
| source | `defval`, `title`, `type` |

The removed `type` role selects the canonical `input.*` callee and is not
emitted into HIR. v4 retains its wider historical tables. v3 does not inherit
the later color, time, or price input types.

The Phase 8 v3 output binder admits the historical `plot` and `hline` parameter
lists. It retains legacy transparency and numeric-style normalization while
reporting the correct source version. Later `display` arguments fail at
analysis. Other pre-v4 output families remain behind their existing focused
boundary until corpus evidence requires a version-specific shape.

## Name And Constant Catalog

The translator catalog revision is `7`. The selected v1-v3 constants are:

| Family | Source surface | Canonical surface |
| --- | --- | --- |
| colors | 17 unqualified named colors | `color.*` |
| color helper | `color(base, transp)` | `color.new(base, transp)` |
| plot styles | `area`, `areabr`, `circles`, `columns`, `cross`, `histogram`, `line`, `linebr`, `stepline` | `plot.style_*` |
| hline styles | `dashed`, `dotted`, `solid` | `hline.style_*` |
| weekdays | `sunday` through `saturday` | `dayofweek.*` |
| chart timeframe | `period`, classification flags, `interval` | `timeframe.*` |
| symbol/bar identity | `ticker`, `tickerid`, `n` | `syminfo.*`, `bar_index` |
| input types | bool, integer, float, string, symbol, resolution, session, source | focused `input.*` markers |

`ema` and `sma` now start at v3 and keep their existing v4 canonicalization.
Every constant has a v4-v6 negative control. `isseconds` starts at v3 because
the historical release boundary differs from the other timeframe flags.

Fallback resolution runs only after ordinary lexical lookup. Persisted tests
cover a user function named `ema` and local representatives from the color,
input-type, plot-style, hline-style, weekday, chart-timeframe, ticker, and bar
identity families. The old `color` helper still obeys the language's existing
built-in-name collision rule; it is routed before the canonical `color()` cast
only when no source binding wins.

## Untyped `na` Contract

For Pine v3 only, an untyped declaration initialized by `na` enters a pending
constraint set. Its first non-`na` scalar reassignment fixes the value kind and
the strongest control-flow qualifier. The inferred type is written back to the
scope, every recorded source binding, and the final HIR symbol. A structured
`v3.untyped_na` emulation record retains the declaration span and inferred
kind.

The following cases emit exactly one `E_LEGACY_V3_NA_INFERENCE` and no HIR:

- no later stable scalar assignment;
- a first collection or object assignment;
- a scalar assignment followed by an incompatible scalar kind.

The same untyped declaration remains invalid in v4-v6 and never emits a legacy
emulation record. Typed modern declarations are unchanged.

## Canonical HIR And Runtime Metadata

Most exact symbol aliases lower to canonical constant built-ins. `n` is
different: `bar_index` is a real series symbol, so lowering binds the alias to
that symbol id and reuses its series id. This prevents a source alias from
turning a live bar value into an unimplemented static constant.

Chart metadata now reads the supplied request environment consistently:

- `syminfo.tickerid`/`main_tickerid` retain the full chart symbol;
- `syminfo.ticker` and `syminfo.prefix` derive their components from it;
- `timeframe.period` retains the normalized chart timeframe;
- minute, second, daily, weekly, monthly, intraday, and D/W/M flags derive from
  the timeframe unit;
- `timeframe.multiplier` derives its numeric multiplier.

Paired v3/v6 runtime tests cover 5-minute, 45-second, 2-day, 3-week, and
4-month chart contexts. The v3 core pair also covers `study`, typed input,
`ema`/`sma`, color alpha, plot/hline styles, conditional untyped-`na`
assignment, `n`, and `interval`. Batch and incremental results are identical,
including output metadata and normalized colors.

## Fixture And Host Evidence

The primary persisted Phase 8 assets are:

- `tests/fixtures/legacy/v3/runtime/core_legacy.pine`;
- `tests/fixtures/legacy/v3/runtime/core_canonical.pine`;
- `tests/fixtures/legacy/v3/runtime/core_bars.csv`;
- `tests/fixtures/legacy/v3/sema/shadowing.pine`;
- the four focused files under `tests/fixtures/legacy/v3/unsupported`;
- `tests/snapshots/runtime_legacy_v3_core.json`.

Semantic tests enumerate every selected constant across v1-v3 and prove that
none resolve in v4-v6. They inspect canonical HIR, inferred symbol types,
translation/emulation records, lexical precedence, historical signatures, and
focused negative diagnostics. Runtime tests compare the legacy/canonical pair,
batch/incremental execution, visual metadata, chart-context identities, and
timeframe classification.

CLI, Python, and WASM analysis tests assert the same v3 dialect, executable
mode, name translations, and `v3.untyped_na` emulation. The host-neutral v3
runtime golden is generated only through the documented CLI snapshot path and
is consumed by Python and WASM tests.

## Corpus Effect

The unchanged 29-item Phase 0 manifest was run twice at build revision
`phase8`; the reports were byte-for-byte identical with SHA-256:

```text
0f61d4d8fa6eed0f94b9d57f83717d6972950285f8ad555595bb10bdf599e94c
```

The manifest SHA-256 remained:

```text
775dd5361a4cbfff954cacb78dc3b66bcd02d5bd6c6689657b8374b7cab0d879
```

Rates retain the denominator of 22 eligible legacy indicators:

| Stage | Passed | Attempted | Eligible denominator | Rate |
| --- | ---: | ---: | ---: | ---: |
| Parse | 22 | 22 | 22 | 100% |
| Analyze | 19 | 22 | 22 | 86.36% |
| Lower | 19 | 19 | 22 | 86.36% of eligible; 100% of attempted |
| Historical run | 19 | 19 | 22 | 86.36% of eligible; 100% of attempted |

Within v3, analysis, lowering, and historical execution are 7 of 7 (100%).
The seven newly passing items cover the color helper, hline style, input/plot
style, MACD-style TA aliases, chart metadata, same-context security, and
untyped `na`. There are no unknown diagnostics, known-unsupported diagnostics,
scope mismatches, or missing required inputs.

The remaining failure cluster contains exactly `legacy_v1_sma`,
`legacy_v2_security_lookahead`, and `legacy_v2_self_reference`, all with
`E_LEGACY_INDICATOR_DECLARATION`. They are the intended Phase 9 boundary.

## Deferred Boundary

- Pine v1/v2 `study` admission, declaration graphs, forward/self references,
  and conversion semantics remain Phase 9.
- Consumer-only or multi-kind untyped-`na` inference is not claimed.
- Other pre-v4 output families retain their focused unsupported boundary until
  their historical signatures are fixture-backed.
- Declaration-level `study(resolution=...)` remains fail-closed under the Phase
  7 whole-program execution boundary.
- Legacy strategies remain permanently out of scope.
- The corpus analyzer still marks incremental, realtime, and reference-output
  comparison as `notRun`; dedicated tests provide incremental evidence for the
  Phase 8 core.

## Verification

The phase gate includes formatting, catalog validation, focused v3 semantic and
runtime tests, CLI/WASM host tests, the Python installed-wheel suite, runtime
and matrix goldens, two deterministic corpus runs, and the repository-wide:

```text
scripts/verify.sh
```

The complete gate passed on 2026-07-19. It included all workspace Rust tests
(including 204 CLI and 526 WASM tests), the WASM Node smoke test, a freshly
built and reinstalled Python wheel with 499 passing binding tests, and the host
parity guard over 726 registered CLI snapshots and 430 required host golden
assertions.

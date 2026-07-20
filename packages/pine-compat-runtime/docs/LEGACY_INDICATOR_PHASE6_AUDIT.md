# Legacy Indicator Phase 6 Audit

## Outcome

Phase 6 makes the result-affecting Pine v4 expression and default-semantics
families executable without translating them into superficially similar modern
constructs. The completed slice covers:

```text
iff(condition, result1, result2)
offset(source, offset)
rsi(x, y) length and removed two-series overloads
v1-v5 strict and/or evaluation
v4 time/time_close weekday session defaults
change, highest, lowest, max, min exact v4 aliases
```

The language version remains part of HIR, and runtime selection is shared by
historical, incremental, and realtime execution. No legacy strategy analysis,
lowering, runtime behavior, or migration path is enabled.

## Historical Contract

The behavior was checked against TradingView's archived
[Pine v4 operator reference](https://www.tradingview.com/pine-script-docs/v4/language/operators/),
the archived [Pine v4 function reference](https://in.tradingview.com/pine-script-reference/v4/),
and the official
[v4-to-v5 migration guide](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/).
The migration guide identifies three result-affecting boundaries implemented in
this phase: removed eager `iff`, removed `offset`, and the removed two-series
`rsi` overload. It also records the session-day default change from weekdays
in v4 to all seven days in v5. The official
[v5-to-v6 migration guide](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-6/)
is the control for strict pre-v6 versus lazy v6 logical operands.

Historical parameter names are bound before canonical validation:

```text
iff(condition, result1, result2)
offset(source, offset)
rsi(x, y)
```

Unknown names, positional arguments after named arguments, duplicates, missing
arguments, and extra arguments stop during analysis at the original call span.
The focused rules run only after lexical values and user-defined functions have
failed to resolve, so a user declaration named `iff`, `offset`, or `rsi` keeps
ordinary source-language precedence.

## Strict `iff` Evaluation

Lowering an old `iff` call to the ordinary ternary HIR node would skip the
unselected stateful branch. Phase 6 instead emits an inaccessible internal
`$legacy.iff` call whose runtime contract is:

```text
condition = evaluate condition once
result1   = evaluate true result once
result2   = evaluate false result once
return condition == true ? result1 : result2
```

Evaluation follows parameter roles even when source arguments are named and
reordered. Both result callsites therefore advance on every reached bar, while
ordinary ternaries remain lazy. A false or `na` condition selects `result2`.
The supported result slice is scalar int/float/bool/string/color/`na`; tuple,
void, collection, and object results fail closed. Branch type and qualifier
merging reuses the analyzer's canonical branch rules.

Compatibility reports record an `expressionDesugar` translation plus an
emulation entry explaining the eager, once-only parameter-order evaluation.
The internal callee contains `$`, so it cannot be invoked from Pine source.

## Structural `offset` Lowering

After historical binding, `offset(source, bars)` is lowered directly to
`HirExprKind::History`. It is not implemented as a registered runtime call and
does not allocate a synthetic callsite. Consequently it uses the same:

- constant and dynamic offset validation;
- non-negative runtime guard;
- `max_bars_back` cap;
- constant-retention and dynamic-retention accounting;
- source-expression series ownership;
- out-of-range and dynamic-`na` results;
- incremental and realtime history state

as canonical `source[bars]`. The translation is reported at the original
`offset` callee span.

## Type-Directed `rsi` Overloads

Pine v4 accepted two meanings for `rsi(x, y)`. The second argument decides the
lowering after semantic type analysis:

| Second argument | Selected behavior |
| --- | --- |
| const/input/simple int | canonical `ta.rsi(source=x, length=y)` |
| series int | historical two-series formula |
| const/input/simple/series float | historical two-series formula |
| bool/string/color/`na` ambiguity | `E_LEGACY_RSI_OVERLOAD` |

The historical formula is evaluated as:

```text
100.0 - 100.0 / (1.0 + x / y)
```

Both numeric arguments are evaluated once. The implementation deliberately
uses the canonical arithmetic evaluator, preserving its finite-number,
division, and `na` behavior instead of adding a second numeric subsystem. The
first argument of the two-series form must be series numeric; invalid forms
stop before HIR is exposed. Length forms lower to `ta.rsi`; formula forms lower
to inaccessible `$legacy.rsi_series` and receive an emulation report entry.

## Session and Logical Defaults

Session parsing now receives an explicit `DefaultSessionDays` policy selected
from `HirProgram.language_version`:

| Version | Omitted day suffix |
| --- | --- |
| v1-v4 | Monday-Friday (`23456`) |
| v5-v6 | Sunday-Saturday (`1234567`) |

Explicit suffixes always override the default. The special `24x7` value always
uses all seven days. `input.session` returns its original string; no compiler or
runtime pass appends a suffix or mutates a host override. The persisted
Friday/Saturday/Sunday/Monday fixture proves both `time` and `time_close`
exclude the weekend only under v4.

The existing runtime version switch for `and`/`or` is now covered across every
v1-v5 language value with stateful EMA calls in right operands. All of those
versions evaluate both operands; a v6 clone of the same HIR short-circuits.
This test avoids parser or alias differences and isolates the runtime version
contract itself.

## Alias Closure and Cache Boundary

The original RSI and iff corpus fixtures also require these exact v4 aliases:

| Legacy name | Canonical target |
| --- | --- |
| `change` | `ta.change` |
| `highest` | `ta.highest` |
| `lowest` | `ta.lowest` |
| `max` | `math.max` |
| `min` | `math.min` |

They are v4-only fallback rules and do not weaken v5/v6 namespace validation.
User-defined functions and lexical symbols retain precedence. The legacy
translator revision is `5`, preventing semantic compile-cache reuse across the
new lowering and runtime-emulation boundary.

## Fixture and Host Evidence

The primary persisted runtime assets are:

- `tests/fixtures/legacy/v4/runtime/expressions_legacy.pine`
- `tests/fixtures/legacy/v4/runtime/logical_strict_legacy.pine`
- `tests/fixtures/legacy/v4/runtime/logical_strict_bars.csv`
- `tests/fixtures/legacy/v4/runtime/session_defaults_legacy.pine`
- `tests/fixtures/legacy/v4/runtime/session_weekend_bars.csv`

The expression fixture covers eager stateful `iff`, constant history, length
RSI, and the two-series RSI formula in one host-neutral output. Dedicated Rust
tests add named/reordered `iff`, lazy ternary controls, dynamic offset input
overrides, negative guards, `max_bars_back`, numeric formula edges, unchanged
session input strings, explicit modern controls, incremental append, and
forming-bar rollback. Semantic tests cover exact HIR shapes, report spans,
float-constant and series-int RSI selection, invalid overloads, user shadowing,
and v5/v6 negative controls.

CLI snapshots are generated only through the repository's documented
`UPDATE_SNAPSHOTS=1` path. The expression, logical, and weekend-session goldens
are consumed byte for byte by CLI, Python, and WASM runtime tests. Host analysis
tests separately assert the `expressionDesugar` translations and behavior
emulations.

## Corpus Effect

The unchanged 29-item Phase 0 manifest was run twice at fixed build revision
`phase6`. The reports were byte-for-byte identical with SHA-256:

```text
998a9a3c092883671c5839d58c336a5f4aa98e69c157a8b23827ad24798d0932
```

Rates retain the denominator of 22 eligible legacy indicators:

| Stage | Passed | Attempted | Eligible denominator | Rate |
| --- | ---: | ---: | ---: | ---: |
| Parse | 22 | 22 | 22 | 100% |
| Analyze | 11 | 22 | 22 | 50.00% |
| Lower | 11 | 11 | 22 | 50.00% of eligible; 100% of attempted |
| Historical run | 11 | 11 | 22 | 50.00% of eligible; 100% of attempted |

Within v4, analysis and historical execution improved from 7 of 12 to 11 of
12 indicators (91.67%). The newly passing items are exactly
`legacy_v4_iff`, `legacy_v4_offset`, `legacy_v4_rsi_overload`, and
`legacy_v4_session`. The only remaining v4 failure is
`legacy_v4_security`, which is the Phase 7 multi-timeframe boundary. The other
ten failures are pre-v4 declarations reserved for Phases 8 and 9.

The corpus analyzer still does not attempt incremental, realtime, or
reference-output comparison stages. Those states remain `notRun` and are not
inflated into the compatibility rate; this phase supplies separate executable
tests for incremental and realtime behavior.

## Deferred Boundary

- Legacy `security`, requested-context evaluation, lookahead defaults, and
  declaration-level timeframes remain Phase 7 work.
- Pine v1-v3 declarations, constants, symbols, and type compatibility remain
  Phase 8/9 work even though shared `iff`/`offset`/`rsi` rules are version-ranged
  for those future dialects.
- Tuple/object/collection `iff` results are outside the current fixture-backed
  scalar slice.
- Exchange-timezone defaults and named exchange sessions remain outside the
  existing time/session contract.
- The legacy compatibility path remains indicator-only; legacy strategies are
  permanently out of scope.

## Verification

Targeted semantic and runtime tests, HIR shape checks, dynamic history guards,
historical/incremental/realtime parity, conformance validation, deterministic
corpus runs, and CLI snapshot generation passed. The complete
`scripts/verify.sh` release gate then passed, including Rust workspace and doc
tests, all 517 WASM tests, all 491 installed-wheel Python tests, the 295-file
structural guard, the nine corpus-analyzer tests, host parity over 724
registered CLI snapshots and 428 required Python/WASM golden assertions, and
the Node WASM smoke test. The initially inlined structural `offset` lowerer was
also extracted from the recursive general-expression lowerer after a deep
matrix-call fixture exposed excess stack-frame growth; the exact regression
fixture and the full gate pass with the isolated helper.

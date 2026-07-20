# Legacy Pine v4 Indicator Profile Closeout

## Release Decision

The Pine v4 indicator profile closes as **preview**, not stable. Direct
execution is enabled automatically from `//@version=4` for the exact
conformance-listed subset. This is not a claim that every v4 indicator or the
whole v4 language runs.

The deciding limitation is evidence breadth. The frozen original corpus has
12 eligible v4 indicators, below the execution plan's provisional stable gate
of 50 authorized scripts for the profile. No external reference-output oracle
is available. Passing the current corpus at 100% therefore proves the committed
subset, not general compatibility.

## Closed Surface

The preview includes the fixture-backed forms of:

- `study(...)` metadata that lower safely to canonical indicator HIR;
- historical `input(...)` overloads and eleven documented v4 input type
  markers with canonical callsite ids and host overrides;
- the conformance-listed unqualified TA/math aliases and collision precedence;
- `plot`, marker/arrow, OHLC bar/candle, `hline`, both `fill` families,
  `bgcolor`, and `barcolor` historical roles and transparency behavior;
- strict `iff`, structural `offset`, the type-directed historical `rsi`
  overload, strict logical evaluation, and weekday session defaults;
- same-context and host-provided same-or-higher-timeframe `security` for the
  documented provider/expression subset.

All hosts select this behavior from the source version. No `legacy` option,
source rewrite, or migration preview is involved.

## Execution Evidence

The release registry contains nine v4 rows: eight complete runtime fixtures
and an additional daily MTF corpus source. Every row passes:

- semantic admission as v4 indicator HIR;
- historical batch execution;
- incremental append equality with batch;
- realtime historical handoff equality with batch;
- a mutated forming update, replacement forming update, rollback, and final
  confirmed equality with batch;
- its declared request provider/chart context where applicable;
- a deterministic retained-value ceiling of 4096 values.

The Phase 11 CLI profile measured a maximum of 90 retained values among v4
rows. Per-fixture end-to-end CLI analysis medians ranged from approximately
2.055 ms to 3.764 ms on the audit machine. Timing is observational and not a
release gate; the storage ceiling is asserted in tests.

CLI-owned runtime and complete-analysis goldens retain Python/WASM parity for
representative v4 inputs, outputs, expressions, sessions, and security. Public
analysis/runtime schemas remain versions 4 and 8.

## Corpus Evidence

The fixed v4 corpus result is 12 of 12 for parse, analyze/lower, and historical
run, with no unknown diagnostics, crash, hang, or scope mismatch. The corpus
manifest is unchanged from Phase 0 and all rows use the `original` license
class. The report is privacy preserving and contains no source text or source
paths.

## Explicit Boundaries

The preview excludes at least:

- legacy strategies and all `strategy.*` execution;
- unsupported `study(resolution=...)`, `resolution_gaps`, and other unlisted
  whole-program declaration behavior;
- lower-timeframe `security`, unsupported requested expressions, missing
  provider streams, and any MTF shape not listed in conformance;
- historical built-ins, overloads, output arguments, and type differences that
  have no positive conformance row;
- a claim of TradingView output equivalence where no external reference oracle
  exists.

To become stable, the profile still needs a frozen authorized corpus of at
least 50 representative v4 indicators, reference-oracle coverage where
available, continued execution-mode/provider parity, and no qualifying unknown
diagnostic cluster. Difficult eligible scripts must not be removed to improve
the denominator.

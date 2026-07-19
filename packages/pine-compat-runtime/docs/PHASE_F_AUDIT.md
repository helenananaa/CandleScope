# Phase F Request Platform Audit

Phase F is closed for the current fixture-backed `request.security` and
multi-timeframe subset. Future request work should proceed as targeted
maintenance unless it widens the supported request surface with syntax,
semantic analysis, runtime behavior, host APIs, fixtures, matrix metadata, and
release verification in one small change.

## Completed Slices

- Slice 1, request provider scaffold:
  `d96f645 Add chart metadata and request provider scaffold`.
  Runtime execution gained a host-neutral `RequestEnvironment`, chart metadata,
  request keys, timeframe parsing, requested-bar validation, and immutable
  in-memory provider support without accepting `request.*`.
- Slice 2, same-context `request.security`:
  `fe1f01a Add same-context request.security subset`.
  The first supported form evaluates scalar side-effect-free expressions when
  symbol and timeframe match the chart context.
- Slice 3, host dataset injection:
  `d6ae062 Add request host dataset injection`.
  Rust runtime, CLI, and Python can inject provider bars through the shared
  request contract. At Phase F close, WASM intentionally remained
  diagnostic-only for provider data injection; Phase T later adds the stable
  WASM JSON host shape for the same provider-backed subset.
- Slice 4, requested-context evaluation:
  `bd5c829 Add requested context evaluation cache`.
  Provider-backed expressions execute in an isolated requested-context runtime
  and cache deterministic results by callsite, request key, and expression
  identity.
- Slice 5, higher-timeframe alignment:
  `d1fbd44 Add higher timeframe request alignment`.
  Same-or-higher-timeframe provider requests gained default
  `gaps_off`/`lookahead_off` alignment.
- Slice 6, lower-timeframe boundary:
  `e2c35a4 Resolve lower timeframe request boundary`.
  Lower-timeframe `request.security` and `request.security_lower_tf` remain
  unsupported with stable diagnostics instead of partial array semantics.
- Slice 7, public host contract hardening:
  `f073509 Harden request host contract`.
  CLI/Python fixtures now exercise the same chart and requested datasets,
  WASM had a documented diagnostic-only test at Phase F close, and conformance
  validation rejects partial request claims without request-specific fixtures.

## Supported Surface

The compatibility matrix in `tests/fixtures/conformance.tsv` is the source of
truth for request claims.

- `request.security` is partial. Supported forms include same-context identity
  requests for `syminfo.tickerid`/`timeframe.period`, including tuple literals
  made from side-effect-free elements and selected tuple-returning calls
  destructured directly from the request such as `ta.macd`, `ta.bb`, `ta.kc`,
  `ta.supertrend`, `ta.dmi`, and `ta.vwap(source, anchor, stdev_mult)`, and
  host-provided same-or-higher-timeframe expressions for explicit symbols or
  `syminfo.tickerid`.
- Supported provider requested expressions are side-effect-free expressions over
  direct OHLCV/time sources, pure arithmetic and ternaries, history references,
  `na`, `nz`, selected stateless `math.*` calls, fixed-mintick
  `math.round_to_mintick`, `math.sum`, `ta.cum`, `ta.sma`, `ta.ema`,
  `ta.dema`, `ta.tema`, `ta.rma`, `ta.rsi`, `ta.tsi`, `ta.cmo`, `ta.cci`,
  `ta.cog`, `ta.bop`, `ta.ao`, `ta.accdist`, `ta.iii`, `ta.nvi`, `ta.obv`, `ta.pvi`, `ta.pvt`, `ta.wvad`, `ta.max`, `ta.min`, `ta.mfi`,
  `ta.stoch`, `ta.wpr`, `ta.sar`,
  `ta.tr` function calls, `ta.atr`, `ta.highest`, `ta.lowest`,
  `ta.highestbars`, `ta.lowestbars`, `ta.change`, `ta.mom`, `ta.roc`, `ta.range`, `ta.dev`, `ta.vwap`, `ta.rising`,
  `ta.bbw`, `ta.kcw`, `ta.pivothigh`, `ta.pivotlow`, `ta.correlation`,
  `ta.covariance`, `ta.median`, `ta.mode`, `ta.percentile_nearest_rank`,
  `ta.percentile_linear_interpolation`,
  `ta.percentrank`, `ta.stdev`, `ta.variance`, `ta.wma`, `ta.vwma`,
  `ta.swma`, `ta.hma`, `ta.alma`, `ta.linreg`, `ta.falling`, `ta.barssince`,
  `ta.valuewhen`, `ta.cross`, `ta.crossover`, and `ta.crossunder`.
- Provider-backed tuple literals whose elements are in the supported scalar
  subset are supported when destructured directly from the request. Selected
  provider-backed tuple-returning calls are also supported, currently
  `ta.macd`, `ta.bb`, `ta.kc`, `ta.supertrend`, `ta.dmi`, and
  `ta.vwap(source, anchor, stdev_mult)`. Other provider-backed tuple
  expressions remain outside this subset.
- Provider-backed requested expressions run in an isolated requested context.
  Chart-runtime history, `ta.*` callsite state, `var` storage, arrays, drawing
  objects, and outputs are not shared with requested-context evaluation.
- Higher-timeframe requests use default `gaps_off` and `lookahead_off`: a
  requested bar becomes visible only after its close is not later than the
  current chart bar close, missing confirmed requested bars forward-fill the
  last confirmed value, and chart bars before the first confirmed requested bar
  return `na`.
- Same-timeframe external-symbol requests require an exact requested-bar
  timestamp match.

## Host Contract

Core runtime crates perform no file, network, or clock I/O for requests. Hosts
must provide all requested bar streams explicitly through immutable provider
data.

- Rust callers use `RequestEnvironment`, `ChartContext`, `RequestKey`, and
  `InMemoryRequestDataProvider`, or the
  `run_historical_with_request_environment` helpers.
- CLI callers pass repeated
  `--request-bars SYMBOL:TIMEFRAME=bars.csv` options alongside the chart
  `--bars` CSV.
- Python callers pass a `request_bars` dictionary keyed by
  `SYMBOL:TIMEFRAME`, with each value using the same bar dictionaries as chart
  bars.
- WASM callers pass a `requestBarsJson` object keyed by `SYMBOL:TIMEFRAME`,
  with each value an array of `{time, open, high, low, close, volume}` bar
  objects, through `runScriptCsvWithRequestBars`,
  `runScriptCsvWithLibrariesAndRequestBars`, or
  `Program.runCsvWithRequestBars`.

The public cross-host fixture is:

```text
cargo run -p pine-cli -- run tests/fixtures/request/request_security_host.pine \
  --bars tests/fixtures/request/chart_1m.csv \
  --request-bars NYSE:IBM:1=tests/fixtures/request/ibm_1m.csv \
  --request-bars NYSE:IBM:5=tests/fixtures/request/ibm_5m.csv
```

It produces the same request values asserted by the Python binding test:

```text
same timeframe: 30, 32, 34, 36, 38
higher timeframe: na, na, 100, 100, 200
```

## Coverage Evidence

- Runtime request tests cover provider validation, missing data, same-context
  identity, external symbol lookup, requested-context arithmetic/history/TA
  evaluation, deterministic caching, same-timeframe matching, higher-timeframe
  alignment, lower-timeframe rejection, and realtime rollback.
- Semantic tests cover supported request forms, invalid timeframes, unsupported
  optional parameters and request variants, side-effect rejection, unsupported
  requested expressions, and `request.security_lower_tf` diagnostics.
- `crates/pine-runtime/tests/incremental.rs` checks runtime fixtures against
  incremental append execution, so request fixtures participate in
  full-vs-append equivalence.
- CLI tests cover request CSV parsing and the public request fixture. Python
  tests cover equivalent `request_bars` injection. WASM tests cover equivalent
  `requestBarsJson` injection for direct runs, compiled programs, and
  library-source combined runs.
- Matrix validation enforces that partial or supported `request.*` rows cite
  request-specific fixture coverage, and `tests/snapshots/matrix.json` includes
  the narrow `request.security` row plus unsupported lower-timeframe and broad
  request-family rows.

## Verification Results

The Phase F closeout verification command is:

```text
scripts/verify.sh
```

It passed on the closeout workspace. This command includes:

- `cargo fmt --check`
- `cargo clippy --workspace --all-targets -- -D warnings`
- `cargo test --workspace`
- `python3 scripts/check_structure.py`
- `cargo check -p pine-wasm --target wasm32-unknown-unknown`
- `maturin build --manifest-path crates/pine-python/Cargo.toml --out dist`
- `python3 -m pip install --force-reinstall dist/*.whl`
- `python3 -m pytest python/tests`

The request implementation remains split by responsibility. The request
subsystem files are 13-191 lines, and the runtime request dispatch module is
203 lines at closeout.

## Remaining Maintenance Tails

These are not blockers for closing Phase F:

- WASM request dataset injection has a stable Phase T JSON host shape for the
  current provider-backed subset; future work should keep that host shape
  synchronized if request semantics widen.
- `request.security_lower_tf` remains unsupported until typed array return
  semantics and public host output shapes are designed together.
- Lower-timeframe `request.security` remains runtime-rejected; no intrabar
  selection rule is claimed.
- Optional `request.security` parameters, explicit `gaps`/`lookahead`, custom
  merge behavior, currency conversion, ignore-invalid-symbol behavior, and
  advanced request families remain unsupported.
- Provider expression local aliases, UDF calls, output/drawing side effects,
  input declarations, array mutation, and other side-effecting requested
  expressions remain unsupported.

## Recommended Next Stage

Do not broaden request support by changing only runtime alignment or only a
host binding. The next request slice should first pick one maintenance tail,
define its public contract, then add fixtures, semantic validation, runtime
behavior, host coverage, conformance metadata, docs, and release verification
in the same change.

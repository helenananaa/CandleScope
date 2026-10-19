# Pine host completion goal

Status: active. Continue the original user goal: CandleScope host gaps first,
then related interpreter work directly in `E:/projects/pine-interpreter`.
The mistakenly relayed scope-narrowing instruction was withdrawn by the user.

## Source and artifact identities

- Host worktree: `E:/CodexData/worktrees/pine-host-adaptation/CandleScope`,
  branch `codex/pine-host-adaptation`.
- Pre-alignment task checkpoint: `2a41db7e069c9c2a8c79d410a0820c2993f3993c`,
  retained at `refs/codex/checkpoints/pine-host-before-main`.
- Verified main: `7e34d54149f8fcb20753a54b9646f8982d336a33`, merged without
  conflicts at `e134d86742e6bcd32825e12bdb8600f8be0824b2`.
- Original main checkout remains at `1a2a0189` with its 19 existing local changes;
  this task did not modify that checkout.
- Core branch: `codex/pine-host-completion`, based on `b9200480e`, now committed
  at `40a1ac8d418b89224c1fa9c268039d95a38c2ebd`.
- Current core wheel: `.local/host-completion/symbol-qualified-wheels/` in the core repo.
  SHA256: `c3e8f517c625b66ec174b42ba09e6b1535903d0a49a1bcb1b48aa3cabb99717b`.
  It is installed only in the task's `output/pine-host/phase3/venv`.
- Package version remains `0.3.2`; use the artifact/source identity and
  `EXTERNAL_CLOCK_SCHEMA_VERSION == 1` and `SYMBOL_METADATA_SCHEMA_VERSION == 1`,
  rather than the version alone. The previous clock-only candidate and receipt
  remain preserved separately.
- Final receipts and logs: `output/pine-host/phase3/`. Official runtime catalogs
  and global plugin activation remain unchanged.

## Implemented host work

- Chart `calc_on_order_fills` now uses the negotiated `pine-chart/2` causal
  aggregate-trade profile. Actual fills update logical ownership before Pine
  observes the account; callback orders wait for a later print. Each pass freezes
  its forming OHLCV, execution clock and visible requested-data prefix. Restore
  covers an unconfirmed pass group. The report records this execution profile
  and callback count, with `tradingViewEquivalent=false`.
- Chart spot net profit no longer treats purchased inventory as a realized loss.
  The failing actual-worker receipt is retained in `chart-fill-spot-before.log`.
  The actual account callback tests pass after using the workbench's realized
  net-profit formula. Auxiliary mark/funding events also close earlier signal
  bars before changing account state; `chart-fill-mark-boundary-before.log`
  retains the reproduced future-mark leak. Restoring a newly produced checkpoint
  after auxiliary confirmation preserves decision/fill/ledger/report hashes.
- Complex drawing/plot output, indicator library imports and frozen dependency
  identities; chart strategy libraries and workbench imports use the same
  validated source graph. Renderer work includes native lines, labels, boxes,
  polylines, linefills, tables and additional plot families.
- Indicator requested data resolves inherited selectors, exact exchanges and
  declared finite dynamic/nested contexts, preserving explicit market types.
  Local confirmed auxiliary candles are bounded; missing data is diagnosed
  without automatic backfill or market substitution.
- Effective FX providers are validated and frozen into indicator/native inputs.
  Native batch/replay/seek tests cover effective times. Currency-dependent reads
  require actual quote metadata. Foreign-account conversion remains rejected by
  the authoritative CandleScope ledger, which does not implement it.
- Replay script fallback carries one captured session/track/data epoch, source
  sequence and inclusive revealed boundary. HTTP compute checks it against one
  durable metadata read per batch, supplies the virtual execution clock and
  clips requested data to that observation. Superseded replies are discarded.
- Forming-chart requested data now reaches the core's ordered confirmed intrabar
  feed: seed prior history, then deliver only observed confirmed intrabars.
  Both scalar security requests and lower-timeframe arrays use that feed.
- Chart market reductions support percentages of the actual host position and
  treat a close on an already flat account as a no-op. Provider restore retains
  actual account history and execution timestamps.
- Chart execution planners preserve explicit market type. Binance USDM/futures
  uses its perpetual `.P` identity; spot retains its identity. Indicator aliases
  follow the same rule and map back only to their proven storage instrument.
- Chart and workbench external evaluation accept explicit execution clocks.
  Prefix transport negotiates clock append support, rebases historical clock
  corrections and clips clock arrays with replay/feedback prefixes. Native
  replay uses its frozen clocks; scheduled fill passes retain their own times.
- Chart Pine now accepts pinned local requested datasets through both direct
  run creation and automatic preparation. Dynamic symbols, library requests,
  higher-timeframe values and lower-timeframe arrays reach the actual isolated
  evaluator and authoritative host fills. Only confirmed auxiliary bars at or
  before the current observation are supplied. Limits are 16 contexts and
  100,000 combined auxiliary bars; missing data requires preparation.
- Checkpoints retain requested revision/hash references, not duplicated market
  arrays. Restore can read the same immutable revision after the dataset's active
  revision changes. The ordinary dataset-selection API still rejects stale
  active selections; pinned reads explicitly opt into revision recovery.
- Requested instrument metadata is frozen through chart/native inputs and
  indicator data settings. Indicators can use exact-market cached metadata or
  explicit values. Cross-venue inputs preserve their own exchange/market type;
  Binance perpetual aliases resolve only against the declared perpetual market.
  Price-grid, currency and quantity-dependent reads diagnose missing metadata.
- Chart Pine now negotiates `ORDER_INTENT` for direct and automatically prepared
  runs. The Host planner reuses actual order allocation and kernel matching for
  price orders, pyramiding, ID-specific partial closes, OCO brackets,
  cancellation and replacement. New compile/run identities freeze the order
  contract and matching/planning implementation. Legacy target-position runs
  retain their market-order profile.
- Script IDs now bind to accepted Host order receipts, rather than predicted
  numeric IDs. Earlier rejected submissions cannot misattribute later fills.
  The shared workbench allocator receives the same repair. Host risk remains
  active at submission and is rechecked against the live ledger before matching.
- Chart provider, kernel, policy and logical-order checkpoints restore together.
  Controlled interrupted/resumed execution preserves fills, orders, entry
  allocations and decision/fill/ledger hashes. Pending submission tags also
  survive a snapshot taken before physical order admission.
- Completed-bar Pine decisions can use the aggregate-trade execution clock;
  a controlled actual-engine case fills a limit entry on the next print and
  advances/fills its trailing stop between signal bars. Intrabar script callbacks
  remain separate goal work. Interface and limits: `docs/pine-chart-orders.md`.

## Interpreter interface addition

Rust exposes `append_external_bars_with_execution_times`; Python adds optional
`execution_times` to `Program.run_external` and `ExternalSession.append`.
The caller supplies timestamps; the core does not access a host system clock or
CandleScope services. Batch/append equivalence, decoding failures, empty append,
feedback preservation and fill-pass clock precedence are tested.

The core also accepts host-owned symbol metadata through
`RequestEnvironment::with_symbol_contexts` and Python/WASM `$symbolMetadata`.
Requested grids, quote currencies and decimal quantity precision survive
different timeframes, nested requests back to the root, historical sessions,
external append and ordered intrabar evaluation. Literal symbols in dynamic
nested scalar requests are admitted. All acquisition and persistence remain in
the host. Interface details: core `docs/SYMBOL_METADATA_INPUT.md`.

## Validation

- Current callback/Host gate: 120 passed, 16 mixed/non-Pine cases deselected in
  `chart-fill-host-final.log`. This includes eight actual-worker callback cases:
  authoritative spot/derivative account observations, threaded adapter execution,
  same-print ownership, unconfirmed-group recovery, incompatible-mode admission,
  and requested data/metadata at the last millisecond of a bar.
  Shared contract-clock/account/sensitivity group: 59 passed in
  `chart-fill-contract-clock-final.log`. Existing kernel/account/recovery group:
  57 passed, one optional-native-row module skipped, in
  `chart-fill-kernel-regression.log`. Bridge group: 69 passed, 12 extension cases
  skipped, in `chart-fill-bridge-final.log`. The core and frontend are unchanged;
  their earlier gates below are inherited evidence. Installed bridge files and
  the unchanged core binary are reconciled in `chart-fill-installed-proof.json`.
- Earlier rich-chart gates are recorded in `rich-chart-host-final.log`,
  `rich-chart-kernel-recovery-regression.log`, `rich-chart-types-qualified.log`
  and `rich-chart-frontend-regression.log` under `output/pine-host/phase3/`.
  Order integration covers 12 actual-engine cases. Shared allocation controls
  include BAR, trade and book admission after an earlier rejection.
  Selected Pine/Host group: 148 passed, 26 mixed/non-Pine cases deselected.
  Existing kernel/account/recovery group: 61 passed; one native-row optimization
  module skipped because its optional extension is not built for this test
  environment. Frontend
  backtest group: 225 passed; UI/Node typechecks passed. The core remains at
  `40a1ac8d4` with its prior complete gate; no interpreter source changed here.
- Current complete core gate: 7,903 Rust tests, 1,700 fresh-wheel Python tests,
  172 tooling tests, formatting, Clippy, structure and host-parity guards, and
  actual WASM/Node execution. The installed candidate independently passed all
  1,700 Python tests. Logs: core `.local/host-completion/symbol-metadata-*.log`.
- Current host group: 119 passed, 4 non-Pine profiles deselected. Bridge suite:
  69 passed, 12 Renko-extension cases skipped. Chart requested-data integration
  includes 11 actual-engine cases, including HTTP, preparation launch, queued
  fills, foreign grids and pinned revision restore.
- Frontend backtest group: 225 passed; latest metadata/run/indicator group:
  34 passed. Typechecks and the 30-locale catalog check passed.
- Playwright checked the actual auxiliary-input component: venue preservation,
  metadata freezing, invalid quantity precision and correction, with zero
  browser errors/warnings. Screenshot:
  `output/playwright/pine-requested-metadata.png`. Temporary helpers were removed.
  This remains component validation, not packaged-app acceptance.
- Earlier clock-only core gate: 7,901 Rust tests, 1,686 tests against a freshly built
  wheel, 172 tooling tests, formatting, Clippy, source structure, binding golden
  checks and generated WASM/Node execution. Focused external Python suite: 41.
- Before final-wheel replacement: combined host group 135 passed; rich Pine host
  group 34 passed; bridge plus host-input group 76 passed and 12 Renko-extension
  cases skipped. Chart/provider, workspace-M9 and chart-Pyne group: 38 passed.
- Final-wheel bridge suite: 65 passed, 12 Renko-extension cases skipped.
  Final-wheel combined backend integration: 174 passed, 46 deselected (mixed
  Pyne/plugin profiles excluded from the Pine candidate scope).
- Frontend replay: 594 passed; clock/API group: 31 passed. UI and Node typechecks
  passed. Existing 30-locale catalog check passed.
- Main's funding/cohort/advance regressions: 44 passed after main alignment.
- Controlled replay tests use durable SQLite and isolated installed Pine workers,
  with an auxiliary-market fixture containing past and future rows. Windows of
  1/128/628 bars, retry, restart and future market/FX append preserve past output.
- Playwright input-component harness checked explicit contexts, invalid JSON and
  correction, state updates and zero browser errors. Screenshot:
  `output/playwright/pine-goal-data-inputs.png`. Helpers were stopped. This is
  component validation; packaged-app acceptance remains separate.
- Ruff passes on changed paths with the existing `external.py` lambda-style
  warning excluded. Diff whitespace checks pass.

The first core gate reused a syntax-fixture executable containing the removed
`pine-external-incremental` worktree path. All 27 failures were missing fixture
files. After verifying the Cargo target lies inside the core workspace, only
`pine-syntax` rebuildable artifacts were cleared; 27/27 fixtures and the complete
rerun passed. The original failure log is retained. Backend and plugin suites run
in separate processes because their test helpers both import a `scripts` module;
the mixed collection failure is also retained.

Retained failures include the first symbol-metadata gate's old negative
assertion for literal nested requests, now promoted to an executable positive
control with distinct provider data. A host replay test also read its record
before taking the job-completion lock; reading both atomically fixed the race.
The full host rerun passed. Earlier draft-test mistakes and their logs are kept.

The first rich-order cross-module run included two mixed-engine cases that
require an installed Pyne adapter, which this Pine candidate environment does
not contain. Their failures are retained; the selected Pine gate explicitly
excludes them and the parameterized Pyne profiles. An early allocation fixture
also omitted the BAR kernel's last observed reference price; it now supplies
that observation. The corrected allocation group passes.

## Remaining goal work

1. Finish chart script intrabar callbacks, process-on-close, `strategy.order`
   and Pine risk-rule semantics through the authoritative Host matcher. Chart
   closed-bar rich orders and print-clock trailing stops are connected.
   Requested datasets are connected; growing requested prefixes currently rebase
   the evaluator and need a causal incremental provider-update contract for
   scalable execution. Chart fill callbacks now have a causal observed-print
   contract and forming-pass checkpoint recovery; TradingView historical final-
   OHLCV callback parity remains unqualified. The current upstream docs also
   describe `calc_on_every_history_tick`, requiring a fresh core/host audit.
   Rich-order cost sensitivity requires independent Host allocation and script
   resimulation per scenario; generic frozen-order matrices are explicitly
   withheld with `PINE_ORDER_RESIMULATION_REQUIRED`.
2. Workbench `CANDLESCOPE` account restoration into native replay remains
   explicitly unsupported. It needs a host-account recovery contract. Tested
   chart-provider restore and native-account replay are separate paths.
3. Remaining display destinations and symbol/session/chart metadata, keeping
   unsupported diagnostics until the real host capability is connected. The
   tick-only bridge uses a reduced rational grid; exact TradingView minmove/
   pricescale representation and arbitrary lot steps need richer host metadata.
   Metadata admission currently requires all selected foreign contexts when a
   corresponding builtin is used anywhere in the script; expression-scoped
   requirements would avoid unnecessary admission failures.
4. Re-audit current core gaps and implement selected missing language/request/
   account semantics. Current development core already provides FX conversion;
   nonunit contract multipliers remain unsupported.
5. Continue broader product and official-reference qualification. Current tests
   do not establish arbitrary TradingView script, pixel, broker-fill,
   protected-library or live-tick equivalence.

Official context semantics reviewed against TradingView's
[chart information](https://www.tradingview.com/pine-script-docs/concepts/chart-information/)
and [other timeframes/data](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/)
documentation. This is documentation alignment, not a fresh TradingView output
oracle for the new metadata tests.

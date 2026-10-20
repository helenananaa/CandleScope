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
- Core branch: `codex/pine-host-completion`, based on `b9200480e`, is at
  `1b506560a5df3ba031b2d1b6d97a86c2061db30b` (declarative risk configuration).
  The retained default candidate still uses
  `dc869e6be26857e34a6cba0edc69943110187d8d` (external closing-tick opt-in).
  Metadata checkpoint `40a1ac8d4` remains in the previous receipt.
- Retained default core wheel: `.local/host-completion/closing-qualified-wheels/` in the core repo.
  SHA256: `0ac745fa781e278a48ffb87a5c5daf0bfe8e6fdef6373b14ab7d886e0324b8f8`.
  It is installed only in the task's `output/pine-host/phase3/venv`.
- The isolated risk/automatic-liquidation candidate uses the core wheel in
  `.local/host-completion/risk-qualified-wheels/`, SHA256
  `88dace3e039039b4e5c57d28988f26708e59cb273ab791eea072e4552049b278`,
  with risk schema 1. Its environment and registry remain under
  `output/pine-host/phase3/risk-stops-venv` and
  `output/pine-host/phase3/risk-stops-runtime-registry.json`.
- Package version remains `0.3.2`; use the artifact/source identity and
  `EXTERNAL_CLOCK_SCHEMA_VERSION == 1`, `SYMBOL_METADATA_SCHEMA_VERSION == 1`
  `EXTERNAL_ORDER_SCHEMA_VERSION == 2` and `EXTERNAL_CLOSING_TICK_SCHEMA_VERSION == 1`,
  rather than the version alone. The previous clock-only candidate and receipt
  remain preserved separately.
- Final receipts and logs: `output/pine-host/phase3/`. Official runtime catalogs
  and global plugin activation remain unchanged.

## Implemented host work

- The Workbench-control checkpoint passed 424 Host cases (41 scoped exclusions),
  176 kernel/risk/contract checks and 75 bridge checks (12 optional Renko skips).
  Counts overlap. Source and test hashes were frozen across the final full gate.
  The current local candidate is isolated in `workbench-control-venv`, with
  `workbench-control-runtime-registry.json` and
  `workbench-control-candidate-receipt.json` under `output/pine-host/phase3`.
  Core source/binary, prior candidate environments and the original checkout
  remain unchanged by this phase.
- Workbench Pine Host-account runs now freeze execution settings and all six
  declarative risk rules under `candlescope.pine-workbench-control/1`. BAR/tape/
  book clocks feed real account/fill observations into the shared controller.
  Synthetic closing scheduling retains visible quotes, consumed depth and sample
  age restrictions; closing callbacks and risk state survive replay restore.
  The candidate remains isolated in `workbench-control-venv` and its dedicated
  runtime registry. See `pine-workbench-controls.md` for scope and limits.

- Chart V2 automatic account liquidation now publishes the actual ledger-backed
  settlement through entry allocation, financial fills, completed trades and
  equity samples. Ordinary fill then immediate liquidation exposes both actual
  account states. Aggregate-trade Pine fill callbacks use observed forming bars
  or persist a deferred callback until a real next trade; checkpoints preserve
  the settlement proof and queue. Independent cost scenarios reexecute this path.
  See `pine-account-liquidation.md` for the declared model and remaining official
  margin-liquidation qualification boundary.
- Pine Workbench `CANDLESCOPE` replay now restores the actual Host kernel,
  account, pending orders, entry/OCA allocation and execution cursor. It validates
  reconstructed evaluator output before matching future events, commits account
  and result journals atomically, and restores full/sampled book consumption and
  queue state. Backward seek, saved snapshots, process restart and HTTP/UI paths
  use the negotiated `candlescope.external-replay/1` contract. Restart coverage
  recreates the replay service from SQLite and launches a fresh evaluator process.
  Native-account
  replay keeps its own existing behavior. Details: [Workbench replay](pine-workbench-replay.md).
- Chart BAR and aggregate-trade runners now negotiate explicit simulated closing
  ticks for `process_orders_on_close=true`. Matching uses only the revealed close,
  taker fees, market/stop slippage and explicit Host latency. V2 closing capacity
  subtracts all quantity already filled in the bucket from the bar participation
  allowance. Reports disclose synthetic liquidity and label simulated closing
  fills separately from physical tape events. Aggregate-trade closing fill
  callbacks retain immutable confirmed market inputs with authoritative account
  updates, ordinary rollback and persistent `varip`; callback orders may use the
  same close under bounded budgets. BAR plus fill recalculation remains
  explicitly unsupported. Workbench closing scheduling is now connected through
  its explicit control contract (`pine-workbench-controls.md`). Independent cost reexecution and
  checkpoint recovery follow the same negotiated closing contract.
- Dual-clock V2 physical fill traces now correctly identify aggregate trades as
  `AGG_TRADE`; the inner tape kernel previously retained its raw-trade default.
  Simulated closing provenance remains `SCRIPT_BAR_CLOSE`. The implementation
  identity changes, so earlier frozen runs/checkpoints must not be relabeled or
  resumed with this new implementation. New mode flags are keyword-only and do
  not shift existing positional constructor parameters.
- Pine V2 robustness matrices now use independent interpreter, account, Host
  allocation and policy execution for each cost scenario, including legacy
  target-position runs. A fresh baseline must match primary decision/fill/ledger/
  kernel-report hashes, orders, curves and policy/allocation evidence. Prepared
  input plans preserve requested references, libraries, clocks and warmup across
  queued whole-run and isolated-provider execution. Secondary runs remain in
  memory and keep per-step/global deadlines, cancellation and state budgets.
- Relative/trailing exit admission now uses allocated entry costs or the observed
  pre-entry quote. The prior unit-price placeholder could reject valid V2 exits
  on tick/minimum-notional rules; the reproduced failure is retained in
  `pine-cost-v2-debug.log`. Prices still bind to actual allocated fills at match
  time. Matrix rows expose their decision/policy hashes, rejected-order counts,
  ending positions and fill-callback counts. Public report hashes include the
  matrix; primary decision/fill/ledger/order/curve evidence stays unchanged.
- Chart `pine-chart/4` and workbench `pine-external/8` now negotiate external
  order schema 2. Fixed positive-quantity `strategy.order` calls support market,
  limit, stop and stop-limit execution through the authoritative Host allocator.
  Quantities net against existing positions without automatic reversal sizing or
  entry pyramiding. Entry IDs remain available to closes, exits and recovery.
- Entry and generic order OCA groups preserve names and none/cancel/reduce types.
  Peer effects apply after each fill, before Pine callbacks. Partial fills,
  independent same-name/different-type groups, gross reversal caps and V2 margin
  release are covered. Legacy target-position revisions reject generic/OCA
  semantics instead of dropping them. The core only emits order intentions and
  receives explicit account feedback; the Host owns all allocation and fills.

- Chart `calc_on_order_fills` now uses the negotiated chart causal
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

Rust `ExternalExecutionOptions { closing_ticks: true }` and Python's keyword-only
`closing_ticks=True` opt into externally scheduled closing ticks. Repeated
confirmed fill passes must keep bars, clocks and request snapshots identical;
only Host account feedback changes. Default callers still reject on-close
execution. WASM exports a schema marker without adding external-account
execution. The pure core owns validation and rollback, while the Host owns
matching, liquidity, process lifecycle and persistence.

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

- Earlier replay-only Workbench/Host gate: 278 passed, 26 mixed/non-Pine cases
  deselected in `external-replay-host-qualified.log`. This includes the earlier
  chart closing/cost/callback/order/request groups and new Workbench/queue
  checkpoints, account-preserving resume, prefix seeks, SQLite reconstruction,
  worker restarts, spot inventory, imports/requested contexts, HTTP/export,
  cancellation, corrupted snapshots, transcript drift, size budgets and atomic
  account/result rollback. Forward-resume spies reject old market events.
  Nine endpoint receipts captured before the change match all stable public
  fields after it; Host implementation identity and its enclosing seal change.
- Current shared kernel/cost/provider/recovery: 75 passed. Frontend: 226 passed,
  both typechecks and 30-locale catalog guard passed. Playwright operated the
  actual React controls against an isolated real Pine Host service. Cursor
  sequence 1/2/1/2/10 reproduces saved/restored reports and the complete batch
  result, with zero browser errors/warnings. This is not packaged-app acceptance.
  Logs and UI proof: `external-replay-*.log` / `external-replay-ui-proof.json`.
- Core and bridge are unchanged from the closing checkpoint; the installed
  binary/wheel and all 15 bridge sources retain that qualified artifact identity.
  New Host identities include replay orchestration/storage code. Earlier frozen
  runs must retain their original implementation rather than be relabeled.
- Closing Host gate: 210 passed, 22 mixed/non-Pine cases deselected in
  `closing-host-qualified.log`. The 34 added cases cover close-only price
  triggering, explicit latency, shared bucket capacity, pending-order snapshots,
  physical/simulated provenance, callback budgets, old constructor compatibility,
  queued BAR runs, authoritative closing callbacks, OCA reduction, closed-group
  recovery, independent costs, legacy targets, private-flag spoofing and retained
  BAR/Workbench rejection. Shared kernel/cost/provider/recovery group: 75 passed
  in `closing-kernel-protocol-qualified.log`. Lint and diff checks passed.
- The first new physical-fill provenance assertion exposed the inner dual-clock
  raw-trade default; `closing-final-focused.log` retains that failure. The final
  210-case run includes the repaired production path and default-mode regression.
  Earlier draft tests also assumed smoke validation performed run admission;
  the retained failure was corrected to test actual run creation.
- Closing core gate: 7,906 Rust, 1,721 fresh-wheel Python and 172 tooling tests,
  formatting, Clippy, structure/host-parity and actual generated WASM/Node passed.
  Log: core `.local/host-completion/closing-full-gate.log`. The task-installed
  wheel independently passed all 1,721 Python tests. Generated Node bindings
  separately verified closing schema 1 and external order schema 2. These are
  controlled interface checks, not TradingView differential qualification.
- Closing bridge suite: 69 passed, 12 optional Renko cases skipped in
  `closing-bridge.log`. Frontend backtest: 225 passed; UI and Node typechecks
  passed in `closing-frontend-*.log`. The approximation-label guard accepts the
  explicit simulated-close label while rejecting a trade-sequence BAR label.
- Earlier Pine-cost/Host group: 177 passed, 22 mixed/non-Pine cases deselected in
  `pine-cost-host-final.log`. Fourteen cost cases cover fee-dependent decisions,
  relative exits, causal callback/partial-fill and latency changes, warmup, legacy
  targets, spot inventory, historical contract roles, queued whole-run/isolated
  workers, deadlines/cancellation, baseline drift and OCA checkpoint recovery.
  The cost matrix and complete report hash reproduce after recovery. Separate
  generic cost/kernel/provider/recovery regression: 75 passed in
  `pine-cost-kernel-protocol-final.log`. Tick/minimum-notional admission controls
  cover both relative and trailing exits. Lint/diff checks pass.
  At that checkpoint, core, bridge and frontend were unchanged; its earlier
  gates below describe those historical source identities.
- Earlier generic-order Host group: 161 passed, 22 mixed/non-Pine cases deselected
  in `generic-order-host-final.log`. Added API cases cover queued charts,
  preparation launch, all four generic order kinds, OCA effects, and workbench
  BAR/trade/book matching. Actual Pine partial-OCA callback recovery preserves
  all four result hashes. Allocation group: 39 passed in
  `generic-order-allocation-final.log`, including V2 margin release and retained
  reversal caps. Bridge suite: 69 passed, 12 optional extension cases skipped.
- Earlier order-schema core complete gate: 7,905 Rust, 1,714 fresh-wheel Python,
  172 tooling tests, fmt, Clippy, structure/host-parity and actual WASM/Node.
  Log: core `.local/host-completion/order-intents-full-gate.log`. The installed
  candidate independently passes 1,714 Python tests. Generated Node bindings
  expose `externalOrderSchemaVersion() == 2`; this is schema metadata and does
  not imply a WASM external-account execution API. Artifact/source reconciliation
  is in `generic-order-installed-proof.json` and the current candidate receipt.

- Earlier callback/Host gate: 120 passed, 16 mixed/non-Pine cases deselected in
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
  backtest group: 225 passed; UI/Node typechecks passed. At that checkpoint the core was
  `40a1ac8d4`; the order-schema gate above supersedes that core identity.
- Earlier metadata core gate: 7,903 Rust tests, 1,700 fresh-wheel Python tests,
  172 tooling tests, formatting, Clippy, structure and host-parity guards, and
  actual WASM/Node execution. The installed candidate independently passed all
  1,700 Python tests. Logs: core `.local/host-completion/symbol-metadata-*.log`.
- Earlier metadata host group: 119 passed, 4 non-Pine profiles deselected. Bridge suite:
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

1. Finish chart script tick/history-tick callbacks, BAR fill-recalculation
   and Pine risk-rule semantics through the authoritative Host matcher. Chart
   entry direction and maximum-position rules are now wired through the
   explicit entry-risk development contract; see `pine-entry-risk.md`. Four
   session/equity halt rules require the separate explicit stop contract. The new core configuration schema
   is a prerequisite and does not fix native conditional rule registration or
   duplicate-rule aggregation. Candidate qualification is tracked separately
   from the retained 3a08561b installed-environment receipt.
   The unchanged-core native probe in `native-risk-preflight.json` reproduces
   conditional cap 2 yielding position 10 and duplicate caps 2/5 yielding 5;
   these remain genuine core work despite the completed Host rule enforcement.
   The four-stop chart contract now connects market/account/fill observations,
   cancellation and real-capacity reducing closes (`pine-risk-stops.md`). Other
   venue calendars, multi-day BAR consecutive-loss windows, partial-fill official
   oracle and broader fidelity qualification
   remain open. The original default task runtime has not been replaced.
   V2 automatic-liquidation ledger receipts now reconcile ownership, callbacks,
   deferred observations and recovery (`pine-account-liquidation.md`). Their
   declared full-position mark-settlement model still requires separate official
   margin-liquidation and product qualification.
   closed-bar rich orders and print-clock trailing stops are connected.
   Requested datasets are connected; growing requested prefixes currently rebase
   the evaluator and need a causal incremental provider-update contract for
   scalable execution. Chart fill callbacks now have a causal observed-print
   contract and forming-pass checkpoint recovery; TradingView historical final-
   OHLCV callback parity remains unqualified. The current upstream docs also
   describe `calc_on_every_history_tick`, requiring a fresh core/host audit.
   The fresh installed-core probe and current official contract are now recorded
   in `pine-bar-tick-preflight.md`: the history-tick declaration is a core gap,
   while realtime ticks are accepted by the language but blocked by the external
   contract. The next phase must separate historical bar state from final commit.
   That core separation is now implemented in the explicit schedule foundation
   (`pine-external-schedule-foundation.md`), together with heap/drawing and
   price-flow rollback. Explicit transport, IPC acknowledgement, immutable prefix
   comparison and chart-provider schedule checkpoints are now connected through
   both bridges (`pine-external-schedule-transport.md`). Historical BAR fill
   callbacks now use the shared OHLC path on chart V1/spot accounts, including
   full historical observations, risk, independent cost reexecution and durable
   complete-bar recovery (`pine-chart-bar-callbacks.md`). Chart V2 historical
   account-event merging, actual mark authority, shared capacity, partial fills
   and settlement callbacks now use their own contract (`pine-v2-bar-path.md`).
   Realtime ticks and history-tick scheduling remain required.
   V2 cost matrices now independently reexecute scripts and Host allocation;
   larger-history performance and broader product acceptance remain to qualify.
   Simulated closing ticks are connected for chart BAR and aggregate-trade runs,
   including aggregate-trade closing fill callbacks. They do not prove actual
   close-auction liquidity or TradingView broker-emulator equivalence.
2. Workbench Pine Host-account replay, six-rule risk enforcement and closing
   scheduling are connected for BAR/tape/book modes through the negotiated
   control contract. Workbench historical BAR fill recalculation now has an
   independent OHLC path matcher and explicit historical callback schedule;
   see `pine-bar-path.md`. Chart V1/spot callbacks now share the matcher;
   chart V2 integration is tracked in `pine-v2-bar-path.md`. Workbench V2 BAR API
   and replay now consume frozen account data (`pine-workbench-v2-bar.md`);
   settings UI/import, independent cost matrices and V2 print/book paths remain
   to connect. Working-order margin repricing across gaps also needs account-model
   repair; retained partial-fill diagnostics reject negative available balances.
   Pyne external-account
   replay is not advertised. Native-account replay remains a separate path.
   Larger-history account-journal/reconstruction performance and packaged
   Workbench acceptance remain unqualified.
3. Remaining display destinations and symbol/session/chart metadata, keeping
   unsupported diagnostics until the real host capability is connected. The
   tick-only bridge uses a reduced rational grid; exact TradingView minmove/
   pricescale representation and arbitrary lot steps need richer host metadata.
   Metadata admission currently requires all selected foreign contexts when a
   corresponding builtin is used anywhere in the script; expression-scoped
   requirements would avoid unnecessary admission failures.
4. Re-audit current core gaps and implement selected missing language/request/
   account semantics. The external order profile still needs comments/alert
   metadata, zero-quantity no-op parity and non-fixed default sizing. Current development core already provides FX conversion;
   nonunit contract multipliers remain unsupported.
5. Continue broader product and official-reference qualification. Current tests
   do not establish arbitrary TradingView script, pixel, broker-fill,
   protected-library or live-tick equivalence.

Official context semantics reviewed against TradingView's
[chart information](https://www.tradingview.com/pine-script-docs/concepts/chart-information/)
and [other timeframes/data](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/)
documentation. This is documentation alignment, not a fresh TradingView output
oracle for the new metadata tests.

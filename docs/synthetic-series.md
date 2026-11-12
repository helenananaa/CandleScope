# Backend synthetic chart series — issue #150

Live-reference, frozen/result, imported-data and replay charts default to backend
computation for Heikin Ashi, Renko, Point & Figure, Kagi and Line Break. Fixed and existing display-window ATR
settings retain their previous semantics. Issue #150 remains open for the
separate strategy execution, durable checkpoint and scale qualifications.

## Ownership

```text
BarAggregator -> DataManager's admitted base bars/history/revisions
                          |                 |
                          |          SyntheticSeriesService
                          |                 |
                     DataManager public bars / synthetic namespaces
                          |
                       HTTP / WS
                          |
              frontend MarketDataManager.synthetic
                          |
              immutable shared replica + per-chart binding
                          |
              BackendProjectionStore (lineage/renderer mapping only)
```

The synthetic service consumes a narrow source port composed from the existing
bar facade, subscriptions, stream leases and source clock. It does not ingest
exchange data, write ordinary K-line buckets, or call HTTP routes. Computation
uses the existing bounded preparation executor; storage reads use the existing
bounded storage executor. Work for each instance is serial. These are thread
executors; this slice does not establish process-level CPU isolation.

`DataManagerCore.synthetic` also exists in `LOCAL_OFFLINE` mode without a live
market source. The live DataManager supplies its admitted bar port; the offline
core accepts only captured/pinned seeds. Both owners close their leases during
application shutdown.

Backend consumers use `await dm.synthetic.attach(definition)`, then
`lease.snapshot(...)`, `lease.next()` and `await lease.close()`. Identical full
definitions share one computation owner and one upstream lease. Cancelling one
seed consumer cannot cancel another consumer's seed. Terminal delivery failure
fences output and recreates the source subscription before accepting a new
snapshot.

## Distinct calculation semantics

* `display-window/1` requires an explicit source `anchor` and `through`.
  It preserves the old loaded-window initialization and inferred tick / whole
  window ATR behavior. Changing the loaded range selects another definition.
  ATR/tick recalibration announces a new generation. This mode supplies displayed bars and chart indicators, and remains unqualified for strategy execution.
* `anchored/1` requires an explicit initialization anchor. Non-HA transforms
  additionally require fixed parameters and explicit `min_tick`; ATR is rejected. A missing prefix is
  unavailable, never permission to initialize from an arbitrary recent tail.
  Source range/finality must be qualified before output is adopted.

The current `close-source/2` algorithm adds the documented volume allocation.
Both identities include the complete source identity, transformation settings
and algorithm version. The service reuses the source calendar resolved by
DataManager, including session gaps. A continuous crypto calendar is the fallback
only when the source declares that identity. Every expected input in the requested
range must be present; missing calendars for other sources fail explicitly.
Closed inputs must carry DataManager's trusted finality. A controlled session-gap
test is not a claim of live qualification for every provider/calendar.

The API reports `strategy_qualified: false`, including for anchored kernels.
Indicators now default to the current displayed input: ordinary candle/line/area
styles retain admitted OHLCV; the five transforms consume the same shared backend
snapshot as the main chart. Strategy runs and broker execution keep their existing
explicit source contracts. Chart rendering alone does not qualify a strategy input.


## Indicator input contract

`useChartIndicatorRuntime` selects the normal hosted runtime for ordinary price
styles and the shared explicit-bars runtime for transformed charts. Only the
selected runtime receives indicator definitions. Live, imported, review, training,
history-study and quick-review adapters supply the same source identity, loaded
window and settings as their chart. Market studies/order flow retain their own
market data semantics; changing a price style does not transform funding rates.

The indicator input hook leases `MarketDataManager.synthetic`. Builtin and Pine
batch requests include `context.chartInput` with the synthetic request, series ID,
generation and revision. The server attaches the same DM instance, verifies that
exact immutable version, and resolves submitted row keys back to authoritative
OHLCV. A raced revision returns 409; it never substitutes newer prices. The next
displayed revision schedules a fresh calculation. No synthetic indicator opens a
raw-candle hosted subscription or reuses the ordinary hosted result cache.

Non-time-based outputs use numeric execution keys `ordinal + 1` inside the
existing numeric indicator codecs. These are identities, never artificial dates.
Renderer lines/annotations/colors and crosshair legends opt into the display
ordinal axis, preserving distinct values on every same-time brick. Pine drawing
`bar_index` positions use that ordered axis; explicit `xloc.bar_time` positions
continue to use source clocks. Heikin Ashi keeps its source-time axis. Parameter,
source, range, generation and rewind changes invalidate prior calculations while
preserving durable indicator definitions and their original execution target.

Frontend JavaScript receives real source times in `bars[i].time`, plus its ordered
`index`; output values still bind by array position. The bundled Pine source build
adds `ordered-chart-input/1`: equal source times are allowed only in that explicit
immutable indicator mode, every row advances series history, and partial/preview
flags remain unconfirmed. A disposable batch reconstructs preview state per
revision; it cannot reuse mutable candle sessions or run the strategy broker.
Ordinary Pine batches still reject duplicate times. An older engine fails with a
capability diagnostic. Other plugin languages currently have no chart-clock
adapter and fail explicitly; definitions remain visible and editable. They are
never silently run over raw bars or execution keys as dates. Retired Pyne remains
rejected. Explicit Pine requested contexts keep their existing contracts and use
real source times plus the captured revealed cutoff for provider reads.

HA preserves source volume. Other transforms carry accumulated source volume to
the next emitted display cohort and divide it equally across that cohort's rows;
unemitted trailing volume stays pending. This deterministic display allocation
avoids multiplying one candle's volume across many bricks. It is an estimate,
not trade-level brick volume or a claim of TradingView parity. Enlarging a
same-time preview cohort can therefore replace its entire volume-bearing prefix.

## Transport and frontend

* `POST /api/v1/synthetic/query`: a bounded snapshot/page.
* `WS /api/v1/synthetic/stream`: one immutable definition per connection.
  Send the same request body as the first frame. Receive a snapshot followed by
  ordered patches, status changes and explicit resnapshots.
* Transform query/stream requests contain source identity/configuration/range,
  never browser OHLCV. Browser-owned historical views explicitly register a
  bounded displayed prefix through the separate capture endpoint described below.
* Output IDs are series ID + generation + ordinal. Equal source timestamps do
  not deduplicate bricks. Snapshot/page cursors refer to output ordinals and
  validate the generation.
* A patch replaces `delete_count` records starting at `from_index`. Revision
  gaps or incompatible identities require a new snapshot.
* Output carries the existing renderer axis and source-lineage metadata.
  Forming overlays are recomputed from confirmed mathematical state.
* Slow consumers resnapshot independently. Source failure does not invoke
  browser algorithms.

The frontend workspace manager owns shared sockets and immutable replicas.
Each chart binding owns only its source-range demand and display projection.
There is no mutable shared K-line `SeriesWindowStore` for synthetic records:
that store's timestamp index would discard equal-time bricks.

Live charts request `complete_window` snapshots. The service captures one
immutable output generation and sends chunks of at most 5,000 records. The
frontend validates order/generation/revision, then atomically publishes the full
loaded source window (within the 50,000-output calculation limit). Updates queued
during transfer follow that snapshot. Small fixed boxes therefore do not silently
lose the first 5,000+ bricks. Independent output-cursor paging remains available
to backend/HTTP consumers; the UI still navigates through its source-window demand.

## Frozen and replay sources

The optional immutable `origin` is part of the complete series identity:

* `RUN_RESULT` reads the completed run's saved chart and verifies config, report
  and chart receipts. `FROZEN_SNAPSHOT` also binds dataset/epoch/snapshot identity
  to the saved chart that supplied the existing frozen view.
* `LOCAL_DATASET` reads the pinned imported candle revision, not its current
  revision pointer. Resampling stays with the local-data owner.
* `REPLAY` reads only through the training service's history, source-bucket and
  tape-projection boundaries. Identity includes session, track, dataset/history
  epochs, captured public time and source sequence. Tape reads remain sequence
  bound even within the same timestamp/bucket. Forward playback does not change
  an older captured request. Querying a display prefix never mutates an account.
* `CAPTURED_WINDOW` covers browser-owned frozen sources, history study and quick
  trade review. `POST /api/v1/synthetic/captures` admits their already displayed
  prefix, validates OHLC/order/bounds and returns a content identity. Subsequent
  transform requests use that identity. This is explicitly client-captured
  display data, not a trusted exchange revision or strategy input. Hidden future
  rows are not registered. Local-origin policy applies to registration and every
  consumer, including consumers attaching to an existing shared instance.

Immutable owners acquire no live bar subscriptions, stream leases or backfill.
They reuse the normal chunked snapshot protocol, shared frontend replicas and
renderer mapping. Changing a replay cursor or input revision selects another
identity; cancellation and late-response fences prevent adopting the old result.
Historical partial coarse buckets retain their partial flags. Immutable kernels
calculate their complete captured window and reject live mutation, rather than
dropping a partial oldest bucket or promoting it to a trusted close.

Captured copies use a 32-entry LRU within the shared backend memory budget.
They are temporary: active consumers re-register on reconnect after eviction or
backend restart. Pending uploads cancel with their chart; registered input rows
also count against the frontend shared-row budget. This is bounded window work,
not a claim of constant-time stepping or durable synthetic checkpoints.

## Default computation and explicit rollback

Market chart surfaces, including frozen/result and strategy-research charts,
replay training/review, imported candles, history study and quick trade review,
use the backend by default for all five synthetic types. No environment opt-in
is needed. `VITE_BACKEND_SYNTHETIC_SERIES=0` is an explicit build-time rollback
to the old display owner. Backend failure in the normal default never invokes a
browser transform. Pure renderer styles still use original bars. Historical
views retain their source-specific owners and captured clocks while computation
runs on the backend; they are never redirected to current market data.

The chart binding uses the explicit loaded source range to preserve the old
display mode. A source-window prepend/trim/new right edge can therefore require
a new bounded seed. The kernel incrementally advances mathematical state for
eligible tails, but retained array copies, parameter scans and output diffing
still have history-dependent cost. This display-window owner has history-dependent costs. Strategies use the
separate causal cursor described below.

Limits are explicit: 10,000 source rows (also subject to the DM query limit),
50,000 generated outputs, 10,000 bricks per input, 32 shared backend instances,
128 backend consumer leases, 64 MiB estimated shared backend retention, and
bounded consumer queues. The frontend allows 32 shared subscriptions and 100,000
total retained/staged output and captured-input rows. Budget exhaustion reports unavailable/resync rather
than silently truncating a calculation into a complete result.

## Validation and remaining acceptance

See [pinned-source qualification](qa/synthetic-series-pinned-20261112/README.md),
[default-path qualification](qa/synthetic-series-default-20261112/README.md)
and the retained [first-slice record](qa/synthetic-series-150-20261112/README.md).
The remaining issue scope includes durable
checkpoint/restart qualification, additional plugin chart-clock contracts and
additional strategy execution modes, full execution/resource scheduling, independent output-cursor UI paging,
multi-chart performance and native macOS/Windows save/exit/restart evidence.
Retained frontend algorithms remain offline migration oracles and the explicitly
selected rollback path. They
are not an automatic fallback for live backend failures.


## Strategy signals follow chart type by default

The chart tester, research page (including imported/frozen sources), and continuing
Python strategies freeze the current chart appearance into `signal_chart` for
HA, Renko, Point & Figure, Kagi and Line Break. Ordinary candle/line/bar renderer
styles omit this optional field and retain market BAR inputs. Changing chart type
or transform parameters invalidates the current result and automatic-run key.
An already running account retains its frozen definition; it is never switched
mid-run. Special-chart Pine instances select Host matching automatically, with
the native broker option disabled while that chart type is active.

`candlescope.chart-signal-input/1`, algorithm `causal-close-source/1`, reuses the
backend transform price steps against chronological, already closed source bars.
Each confirmed chart row is one provider observation. Provider sequence and Pine
`bar_index` advance per chart row; source timestamps and availability timestamps
remain real clocks. Several bricks may share one timestamp. Warmup counts chart
rows. No generated brick becomes a market event.

The market loop iterates the lazy signal plans in order: evaluate one chart row,
admit its orders, then evaluate the next. Sizing and pyramiding can therefore see
pending orders from earlier bricks at the same close. Existing BAR/tape/book
matching, account marks, fees, slippage, capacity and order eligibility continue
using real prices and market sequence numbers. A source bar without a new brick
still matches working orders. `process_orders_on_close` uses the existing real
closing-price owner, never a synthetic close. Cost scenarios preserve all accepted
orders at a shared market sequence; Pine scenarios recompute the chart signal
clock against independent real accounts.

Causality differs from repaintable display-window output:

- ATR is updated from the known source prefix (initial running mean, then Wilder
  recurrence). A new box size applies to subsequent steps without rewriting past
  decisions. Tick precision is explicit when supplied, otherwise fixed from the
  first known bar and parameters. A display-window ATR recalibration can redraw
  chart history; it cannot reproduce or alter this historical decision trace.
- The unfinished P&F column / Kagi leg is retained as state and becomes a strategy
  close only when a reversal confirms it. Reaching the end of a backtest does not
  confirm an unfinished column. HA, Renko and Line Break emit their confirmed
  source-close outputs. Output volume retains the documented close-source
  allocation estimate.
- Pine `request.security` contexts retain their separately frozen real datasets
  and revealed bounds. The root ticker describes the selected nonstandard chart;
  explicitly requesting the standard symbol does not alias the root bricks.

Pine's explicit `ordered-chart-strategy/1` contract accepts repeated main source
clocks only through the external-account engine entry point. Ordinary candle
entry points still reject duplicate times. Pine indicators retain their separate
ordered-chart input contract. Close-only fixed-history endpoint-sensitive
Workbench programs and whole-market Python batch execution remain explicit
unsupported combinations with chart signals. Event schedules use the separate
observed-price contract below.

The Host planner checkpoint owns the bounded transform cursor (ATR, tick, pending
volume/column and ordinals). Native external replay separately persists the raw
market cursor and chart cursor/transcript, including checkpoints before any brick
exists. Ordinary runs do not acquire synthetic checkpoint fields. Existing
provider/account checksums and commit fences remain the recovery owners.

See [strategy signal qualification](qa/chart-strategy-signals-20261112/README.md).
This qualifies source/local runtime behavior; native macOS save/exit/restart,
Windows, endurance and large-history performance remain separate acceptance work.


## Special-chart fill and physical-tick recalculation

`candlescope.chart-signal-events/1` is selected automatically for special-chart
Pine programs with `calc_on_order_fills` or `calc_on_every_tick`. Both settings
can operate together through one shared chart cursor. This applies to queued
chart Host runs, independent cost accounts, native external Host runs and saved
native replay. No extra rollout switch is required. Source-declared fill
recalculation is effective without a second Workbench checkbox.

The real market loop advances this cursor once per observed price, then executes
the existing real matcher. A fill callback sees the updated account and current
chart row; another callback at the same physical event does not reapply its
price or volume. Confirmed chart rows are evaluated and their plans admitted
serially before the next row. The subsequent ordinary tick callback sees the
same forming row. Multiple bricks can retain the exact same millisecond start;
`bar_index` is their ordinal, not a fabricated timestamp.

- **Actual trade data:** `calc_on_every_tick` requires frozen physical trade or
  aggregate-trade events. Book-assisted modes retain their original trade/book
  ownership, quote constraints and capacity. The report labels this input
  `OBSERVED_TRADE_STREAM` and volume `OBSERVED_TRADE_QUANTITY`. Account/funding or
  book-only updates cannot manufacture a new price print.
- **BAR approximation:** fill recalculation also works on the existing OHLC
  path matcher. The chart sees only the visited price prefix. Its report labels
  price `OHLC_PATH_APPROXIMATION` and volume `LINEAR_TIME_PROXY`; elapsed source
  time allocates the source volume estimate. This mode is not true tick data.
  Special-chart `calc_on_every_tick` with BAR-only data and the historical
  pseudo-tick option fail explicitly.
- **Chart math:** HA recomputes its forming candle from the observed source OHLC
  and prior committed HA values, then confirms at the source close. Renko and
  Line Break confirm crossing rows when the observed price crosses; P&F/Kagi
  confirm on reversal. Their active column/leg is not closed by reaching the end
  of a run. ATR uses completed source bars plus only the currently revealed
  partial range. Actual market tick metadata is frozen before the first step.
- **Pine state:** ordinary realtime variables roll back between previews;
  `varip` persists across observations. Confirmation commits the row. Explicit
  standard-symbol `request.security` remains a separately frozen real dataset,
  revealed only when available; it cannot alias the selected special root.
- **Recovery:** source-bar, physical-event, chart-ordinal and Pine stream cursors
  remain independent. A checkpoint retains the forming row, ATR/math state,
  callback budget, requested-data cursor and evaluator transcript. Restore
  rebuilds evaluator state without replaying any market fill. Fill callbacks
  are bounded to 64 per physical event; crossing batches retain their separate
  chart-row bound.

These observed-price event charts can produce different history from the
close-source strategy contract above and from a repaintable display-window
reconstruction. Choosing a tick/fill schedule freezes that distinction in the
run contract. The execution ledger, marks, fees, slippage, liquidity, eligibility
and `process_orders_on_close` continue to use the existing real-price owners.
Synthetic prices are never substituted into the matcher.

See [event schedule qualification](qa/chart-strategy-events-20261112/README.md)
for the default source artifact and local evidence. This does not establish
installed desktop save/exit/restart, Windows or long-history performance.

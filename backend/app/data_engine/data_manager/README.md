# Data Manager

[中文](README_zh.md)

> Public business facade for CandleScope market data. `DataManager` is the module API/WS/Indicator code should use for K-line queries, cache access, event subscriptions, stream lifecycle, backfill coordination, price snapshots, and maintenance tasks.

## Position In Data Engine

```text
ingestion -> bar_aggregator -> DataManager -> API / WS / Indicator
                         ▲
                         └── backfill -> storage readback
```

`data_manager` is the boundary between low-level data plumbing and application features. External modules should use the package root exports from [__init__.py](__init__.py), not internal services such as `QueryEngine`, `StreamCoordinator`, or `AggregatorBridge`.

## Responsibilities

| Area | Component | Responsibility |
|---|---|---|
| Facade | `DataManager` | Public methods for query, stream, subscription, maintenance, and diagnostics |
| Cache | `KlineCache` | In-memory series cache with size/TTL limits |
| Query | `QueryEngine` | Resolve Cache -> Storage -> Backfill with missing-range metadata |
| Streams | `StreamCoordinator` / `StreamEnsurePlanner` | Start and stop ingestion + bar aggregator targets; share upstream streams across consumer leases |
| Events | `DataEventBus` | Callback and async-iterator event distribution |
| Aggregation Bridge | `AggregatorBridge` | Persist bar events, merge cache, emit `DataEvent` |
| Backfill | `BackfillCoordinator` | Execute repairs, persist/verify gaps, read storage back into cache, emit completion events |
| Backfill Scheduling | `BackfillScheduler` | Demand leases, dedup/merge, chunk scheduling, fairness, pacing and cancellation |
| Backfill Admission | `BackfillHistoryPlanner` | Availability/calendar planning, closed-bar clamping and no-fetch outcomes |
| Custom Query | `CustomQueryEngine` | Query custom intervals consistently |
| Warm Start | `AggregatorWarmStartService` | Seed aggregator state from storage on startup |
| Price | `IngestionPriceSource` / `PriceSnapshotCache` | Lightweight realtime price stream and snapshots |
| Subscription | `SubscriptionService` | Watchlist tiers: `full`, `price`, `none`; persisted full intervals and consumer leases |
| Maintenance | `maintenance.py`, `retention.py` | storage repair, gap scan, retention limits |

## Public API

### Source continuity per subscription

`subscribe()`, `subscribe_async()` and `subscribe_iter()` accept `continuity`:

```python
from app.data_engine.data_manager import ContinuityPolicy, DataEventType

strict = dm.subscribe(on_closed, symbol="BTCUSDT", interval="1m",
    event_types={DataEventType.BAR_CLOSED}, on_recovery=reload_snapshot,
    continuity=ContinuityPolicy("strict", max_wait_seconds=2.0))
live = dm.subscribe(on_live_or_control, symbol="BTCUSDT", interval="1m",
    continuity="gap_aware")
```

The default is `strict`, with a 10-second deadline measured from gap detection.
DataManager-owned K-line pipelines delegate repair to the existing shared
BackfillCoordinator; L5.5 retains its ordered replay filter but does not hold all
consumers behind one REST repair. TradeFlow also delegates to its shared ID repair service, so one strict
consumer does not hold the shared ingress behind REST.

Strict consumers wait in their own bounded EventBus worker/replay window. Only
trusted final rows covering every missing open time release the wait. Missing
bars are delivered in order as `BAR_CLOSED` with `continuity_replayed=True`,
followed by the queued tail. Queued bars received during the gap carry the same
flag; alerts update state without treating catch-up as fresh signals.
Timeout, failed repair, source stop, replay exhaustion, or a deferred durable
receipt regressing behind a replayed close requires a new snapshot
and subscription (`on_recovery` for callbacks, `ConsumerRecoveryRequired` for
iterators). A strict subscription joining an already gapped stream must also
reseed after repair: it did not receive the pre-subscription tail.

Gap-aware consumers receive `SOURCE_GAP` and `SOURCE_GAP_RESOLVED` even when their
event filter excludes them. Bars published while incomplete carry
`detail.source_continuity`; repaired bars are `BAR_AMENDED` when that type is
selected. A resolved control supplies the range for consumers that instead
reload history. This policy requires a consumer that handles these controls;
existing browser protocols are not implicitly switched to it.

The guarantee covers **detected source gaps in final K-line bars**, not initial
history, missing intrabar ticks, or an exactly-once external side effect.
Calendars supply expected open times. Derived intervals get their own affected
bucket ranges and require verified target bars, not merely repaired base bars.
Unsubscribe/cancellation does not cancel shared repair. Wildcard subscriptions
have one delivery worker; use separate handles for independent series latency.
Gap evidence is bounded to 256 records and 10,000 expected bars in total. If
pending evidence would be evicted, strict delivery fails closed until the data
manager is restarted and consumers reseed. Diagnostics are exposed under
`market_data_control_snapshot().source_continuity`.

Common methods on `DataManager`:

| Method | Purpose |
|---|---|
| `start()` / `shutdown()` | Lifecycle |
| `query()` | Query a range, optionally triggering backfill |
| `query_latest()` | Latest N bars |
| `query_before()` | Pagination before a timestamp |
| `get_bounds()` | Storage metadata for a series |
| `scan_storage_gaps()` | Continuity scan without repair |
| `ensure_stream()` | Ensure realtime ingestion + aggregation is running, optionally registered to a consumer lease |
| `release_stream()` | Release a consumer lease without forcing unrelated consumers to stop |
| `subscribe()` / `unsubscribe()` | Callback event subscription |
| `subscribe_iter()` | Async iterator event subscription |
| `on_bar_event()` | Consume `BarAggregator` events |
| `on_bars_backfilled()` | Merge repaired bars after storage readback |
| `get_prices_snapshot()` | Current watched-symbol price snapshots |
| `get_subscription_service()` | Access subscription tier manager |
| `repair_custom_storage()` | Rebuild custom interval rows |
| `scan_and_fill_storage_gaps()` | Manual gap scan and repair |
| `update_retention_limits()` | Update DB/ephemeral retention settings |
| `snapshot()` | Full diagnostic snapshot |
| `market_data_control_snapshot()` | Channel ownership, typed namespaces, readiness, and coverage boundaries |

Channel-specific operations are grouped under typed namespaces:

- `dm.bars`: bar queries, bounds, and stream ensure.
- `dm.market_state`: ticker/mark/funding/open-interest/basis latest and history.
- `dm.trades` and `dm.liquidations`: append-only event access with distinct coverage guarantees.
- `dm.books.partial` and `dm.books.full`: replaceable Top-N versus sequence-gated full-depth books.

The older flat methods remain compatibility wrappers and route through these namespaces.

Example:

```python
from app.data_engine.data_manager import DataManager

dm = DataManager()
await dm.start()

await dm.ensure_stream("BTCUSDT", "1m", exchange="binance", market_type="spot")
result = dm.query_latest("BTCUSDT", "1m", 500, "binance", market_type="spot")

handle = dm.subscribe(callback=on_event, symbol="BTCUSDT", interval="1m")
dm.unsubscribe(handle)

await dm.shutdown()
```

## Public Types

The package root exports the stable facade and contracts:

- Config: `DataManagerConfig`, `CacheConfig`, `QueryConfig`, `EventBusConfig`, `CoordinatorConfig`, `PrewarmTarget`
- Data: `BarData`, `SeriesKey`, `QueryResult`, `MissingRange`, `QuerySource`
- Events: `DataEvent`, `DataEventType`, `SubscriptionHandle`
- Streams: `StreamInfo`, `StreamStatus`
- Storage protocol: `StorageBackend`
- Maintenance/subscription: `MaintenanceBusyError`, `MaintenanceUnavailableError`, `SubscriptionTier`
- Domain facades: `BarDataFacade`, `MarketStateFacade`, `TradeDataFacade`, `LiquidationDataFacade`, `PartialOrderBookFacade`, `FullOrderBookFacade`

## Timestamp And Identity Rules

- Storage and internal engine timestamps are milliseconds.
- `BarData.time` is Unix seconds for `lightweight-charts`.
- `SeriesKey` normalizes symbol to uppercase and exchange/market type to lowercase.
- Binance spot topics remain compact: `BTCUSDT@1m`.
- Non-default exchange or market type is prefixed: `okx:swap:BTC-USDT@1m`, `futures:BTCUSDT@1m`.

## Query Semantics

`QueryEngine` resolves data in this order:

1. Cache, when the requested range is present.
2. Storage, via the injected storage backend.
3. Backfill trigger, when missing ranges are detected and `auto_backfill` is enabled.

`QueryResult` includes:

- `bars`: sorted ascending `BarData`
- `source`: `cache`, `storage`, `backfill`, `mixed`, or `empty`
- `cache_hit`
- `has_more`
- `backfill_triggered`
- `has_tail_gap`
- `missing_ranges`
- `metadata`

API range endpoints add visible-range verification on top of this metadata.

## Stream Lifecycle

`ensure_stream()` is the public way to start realtime data:

```text
ensure_stream(symbol, interval)
        ▼
StreamEnsurePlanner
        ▼
StreamCoordinator
        ├── BarAggregator.add_target()
        └── IngestionFactory.start(on_market_event)
```

The planner chooses the required source streams. For custom intervals, this can mean starting a suitable base interval and registering the requested target interval with the aggregator.

## Backfill Coordination

The component dependency direction is explicit:

- [backfill_contracts.py](backfill_contracts.py) owns request/result values and
  demand priorities. Producers import this module without loading the scheduler
  or coordinator; existing coordinator imports remain compatible re-exports.
- [backfill_history.py](backfill_history.py) plans requests using only the
  availability service and policy resolver. It has no cache or scheduler state.
- [backfill_scheduler.py](backfill_scheduler.py) owns scheduling state and demand
  leases. Execution, durable finalization and completion are injected callbacks;
  the scheduler does not import the coordinator or access storage/cache directly.
- [backfill_coordinator.py](backfill_coordinator.py) composes these owners with
  the engine, persistent gap ledger, cache readback and event delivery. The
  durable finalizer completes before the scheduler releases shared waiters.

`BackfillCoordinator` is deliberately separate from `BackfillEngine`:

- Converts facade/API requests into semantic demands with `reason`, `priority`,
  `requester`, and metadata.
- Deduplicates in-flight requests.
- Merges compatible pending ranges while preserving the highest priority.
- Splits large repairs into chunks; user-visible repairs run newest-first.
- Runs different series concurrently while keeping the same
  `(exchange, market_type, symbol, interval)` serialized.
- Admits no new background chunk while foreground work is active; one already
  running background page may finish before the next scheduling boundary.
- Maintains per-exchange/market token buckets for scheduler-level pacing.
- Keeps rate-deferred foreground work visible to speculative producers, so a
  `Retry-After` wait does not look like idle capacity.
- Persists gap lifecycle in `GapLedger`.
- Handles retry/cancel/shutdown.
- Runs `BackfillEngine`.
- Reads `RepairReport.written_ranges` back from storage.
- Calls `DataManager.on_bars_backfilled()`.
- Emits `BACKFILL_COMPLETED` or `BACKFILL_FAILED`.

API and settings code should trigger repair through DataManager/coordinator, not call `BackfillEngine.run()` directly.

Current demand mapping:

| Source | Reason | Priority |
|---|---|---:|
| `/klines/history?intent=viewport` (default) | `initial_history` | 10 |
| `/klines/range` | `visible_range_gap` | 20 |
| `/klines/history/before` | `visible_load_more` | 20 |
| foreground custom/base warm start | `visible_seed_gap` | 25 |
| ingestion tail gap | `tail_gap` | 25 |
| `/klines/latest` if explicitly enabled | `latest_refresh` | 30 |
| query repair family | `query_*` | 35 |
| price stream daily open | `price_daily_open` | 70 |
| `/klines/history?intent=active_hydration` | `active_history_hydration` | 90 |
| same-symbol interval warmup | `related_interval_warmup` | 100 |
| `SubscriptionTier.FULL` warmup | `full_subscription_warmup` | 110 |
| startup scan | `startup_gap_scan` | 140 |
| background audit | `background_gap_audit` | 160 |

`/klines/latest` is intentionally `auto_backfill=false` by default. On a cold
symbol, first-screen loading is driven by `/klines/history`, and related
intervals are submitted only as lower-priority warmup. Related-interval
admission is debounced per demand scope, waits for a foreground-quiet dwell,
and records successful exact target ranges in a bounded five-minute TTL
registry. A newly closed target range bypasses the older entry; rejected or
failed submissions never poison the TTL.

Active-series hydration is also newest-first, but remains a background lane.
It never coalesces with a viewport parent, so a wide cache fill cannot expand
or inherit ownership of the visible request.

## Events

`DataEventType` values include:

- Bar lifecycle: `BAR_CREATED`, `BAR_UPDATED`, `BAR_CLOSED`, `BAR_AMENDED`, `BAR_EXPIRED`
- Stream lifecycle: `STREAM_STARTED`, `STREAM_STOPPED`, `STREAM_ERROR`
- Backfill lifecycle: `BACKFILL_STARTED`, `BACKFILL_COMPLETED`, `BACKFILL_FAILED`
- Cache/price: `CACHE_PREWARM`, `CACHE_EVICTION`, `PRICE_UPDATED`

Consumers can use callbacks or async iteration:

```python
async for event in dm.subscribe_iter(symbol="BTCUSDT", interval="1m"):
    print(event.to_dict())
```

## Configuration

`DataManagerConfig` groups:

| Section | Important Fields |
|---|---|
| `cache` | `max_bars_per_series`, `max_series`, `prewarm_bars`, `ttl_seconds` |
| `query` | `default_limit`, `max_limit`, `sync_backfill_timeout_seconds`, `auto_backfill` |
| `event_bus` | `subscriber_queue_size`, `emit_bar_updated`, `emit_bar_created` |
| `coordinator` | `auto_start_ingestion`, `idle_stream_timeout_seconds`, `base_interval`, `prewarm_intervals`, `prewarm_symbols`, `prewarm_targets` |

## Maintenance

`DataManager` exposes maintenance through facade methods used by settings API:

- `repair_custom_storage()`
- `scan_and_fill_storage_gaps()`
- `scan_storage_gaps()`
- `update_retention_limits()`
- `retention_snapshot()`

Maintenance methods raise `MaintenanceBusyError` for concurrent conflicting work and `MaintenanceUnavailableError` when a required runtime dependency is missing.

## Tests

```bash
cd backend
python -m pytest -q \
  tests/test_query_engine_paths.py \
  tests/test_backfill_coordinator.py \
  tests/test_data_manager_warm_start_bridge.py \
  tests/test_maintenance_facade.py \
  tests/test_price_subscription_services.py
```


### Other channels and providers

There is no exchange or instrument allowlist in the subscription policy. Existing
plugin capability, market-name, calendar and entitlement checks still apply.
`dm.continuity_contract(key)` reports availability, policies and the exact
guarantee. A history-only provider does not acquire a realtime feed from selecting
this option (the current Twelve Data K-line plugin is history-only).

The `continuity` argument is available on `dm.trades.attach`,
`dm.books.partial.attach`, `dm.books.full.attach`, `dm.liquidations.attach` and
`dm.market_state.subscribe` (also `dm.subscribe_market`). These non-bar APIs opt in
explicitly; omission preserves their existing delivery interface.

- Monotonic-ID trades with authoritative history replay share service repair.
  Strict consumers replay exact missing IDs within one bounded batch wait budget;
  gap-aware consumers inspect `batch.detail.source_continuity` and process
  `batch.corrections`, including empty-record control batches. Replayed strict
  batches carry `continuity_replayed=True`. The budget starts when the consumer
  observes the missing-ID batch. A missing retained range requires resync.
- Full books resume strict delivery only after the engine verifies a new snapshot.
  Partial books and latest market state wait for a fresh valid replacement.
  These contracts guarantee **current state**, not every historical transition.
  Gap-aware status notifications survive latest-wins coalescing.
  If the shared hub exhausts unresolved-gap evidence, strict delivery fails with
  `source_gap_tracking_exhausted`; recreate the owning service and obtain a fresh
  snapshot. Resubscribing to the same hub does not restore the guarantee.
- Observational trades and sampled liquidations only accept `gap_aware`.
  `strict` raises `ContinuityUnsupported`; notifications expose non-exhaustive
  quality and unrecoverable connection breaks without inventing missing events.

Cancellation never cancels shared repair. Existing browser protocols are not
implicitly opted in. Controlled cross-provider tests are not live-exchange
acceptance evidence.

# Backend synthetic chart series — issue #150

Live-reference charts default to backend computation for Heikin Ashi, Renko,
Point & Figure, Kagi and Line Break. Fixed and existing display-window ATR
settings retain their previous semantics. Issue #150 remains open for the
separate shared indicator/strategy, durable checkpoint and scale qualifications.

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
  ATR/tick recalibration announces a new generation. This mode is display-only.
* `anchored/1` requires an explicit initialization anchor. Non-HA transforms
  additionally require fixed parameters and explicit `min_tick`; ATR is rejected. A missing prefix is
  unavailable, never permission to initialize from an arbitrary recent tail.
  Source range/finality must be qualified before output is adopted.

Both identities include the complete source identity, transformation settings
and algorithm version. The service reuses the source calendar resolved by
DataManager, including session gaps. A continuous crypto calendar is the fallback
only when the source declares that identity. Every expected input in the requested
range must be present; missing calendars for other sources fail explicitly.
Closed inputs must carry DataManager's trusted finality. A controlled session-gap
test is not a claim of live qualification for every provider/calendar.

The API reports `strategy_qualified: false`, including for anchored kernels.
This batch does not connect synthetic OHLC to indicator or strategy execution.
Existing indicators still use original bars and their existing coordinate
mapping. Real-price execution and supported language contracts are unchanged.

## Transport and frontend

* `POST /api/v1/synthetic/query`: a bounded snapshot/page.
* `WS /api/v1/synthetic/stream`: one immutable definition per connection.
  Send the same request body as the first frame. Receive a snapshot followed by
  ordered patches, status changes and explicit resnapshots.
* The request contains source identity/configuration/range, never browser OHLCV.
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

## Default computation and explicit rollback

`LIVE_REFERENCE` market chart surfaces, including strategy-research live charts,
use the backend by default for all five synthetic types. No environment opt-in
is needed. `VITE_BACKEND_SYNTHETIC_SERIES=0` is an explicit build-time rollback
to the old display owner. Backend failure in the normal default never invokes a
browser transform. Pure renderer styles still use original bars. Offline/frozen
sources and replay retain their source-specific owners, so a historical view is
not silently redirected to current market data.

The chart binding uses the explicit loaded source range to preserve the old
display mode. A source-window prepend/trim/new right edge can therefore require
a new bounded seed. The kernel incrementally advances mathematical state for
eligible tails, but retained array copies, parameter scans and output diffing
still have history-dependent cost. This is not the final performance or shared
causal strategy-input implementation.

Limits are explicit: 10,000 source rows (also subject to the DM query limit),
50,000 generated outputs, 10,000 bricks per input, 32 shared backend instances,
128 backend consumer leases, 64 MiB estimated shared backend retention, and
bounded consumer queues. The frontend allows 32 shared subscriptions and 100,000
total retained/staged output rows. Budget exhaustion reports unavailable/resync rather
than silently truncating a calculation into a complete result.

## Validation and remaining acceptance

See [default-path qualification](qa/synthetic-series-default-20261112/README.md)
and the retained [first-slice record](qa/synthetic-series-150-20261112/README.md).
The remaining issue scope includes durable
checkpoint/restart qualification, pinned immutable replay inputs, indicator and
strategy adapters, full execution/resource scheduling, independent output-cursor UI paging,
multi-chart performance and native macOS/Windows save/exit/restart evidence.
Retained frontend algorithms remain offline migration oracles, source-specific
offline/replay implementations and the explicitly selected rollback path. They
are not an automatic fallback for live backend failures.

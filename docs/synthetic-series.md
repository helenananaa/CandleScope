# Synthetic series candidate — issue #150

This is the first migration slice: close-source Renko (fixed box and the
existing display-window ATR rule) and Heikin Ashi. Point & Figure, Kagi and Line
Break are not migrated by this change. Issue #150 remains open.

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
* `anchored/1` requires an explicit initialization anchor. Renko additionally
  requires fixed `box_size` and `min_tick`; ATR is rejected. A missing prefix is
  unavailable, never permission to initialize from an arbitrary recent tail.
  Source range/finality must be qualified before output is adopted.

Both identities include the complete source identity, transformation settings
and algorithm version. A source is currently admitted only for crypto with a
continuous calendar, and every expected source row in the requested range must
be present. Sparse/no-trade and session-calendar qualification remain open.
Closed inputs must carry DataManager's trusted finality.

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

The current renderer retains the latest 5,000 output records. Snapshot `before`
and `total` expose the older output; no complete-history claim is made. Deep
ordinal paging in the product UI remains open.

## Candidate rollout

`VITE_BACKEND_SYNTHETIC_SERIES=1` opts a matched frontend/backend build's
`LIVE_REFERENCE` market chart surfaces into this candidate for HA and Renko.
It is off by default pending installed-package acceptance. Other chart types,
offline/frozen sources and replay keep their existing owners. Enabling the
candidate never silently falls back when its backend is unavailable.

The chart binding uses the explicit loaded source range to preserve the old
display mode. A source-window prepend/trim/new right edge can therefore require
a new bounded seed. The kernel incrementally advances mathematical state for
eligible tails, but retained array copies, parameter scans and output diffing
still have history-dependent cost. This is not the final performance or shared
causal strategy-input implementation.

Limits are explicit: 10,000 source rows (also subject to the DM query limit),
50,000 generated outputs, 10,000 bricks per input, 32 shared backend instances,
128 backend consumer leases, 64 MiB estimated shared backend retention, and
bounded consumer queues. The frontend allows 32 shared subscriptions and 20,000
total retained output rows. Budget exhaustion reports unavailable/resync rather
than silently truncating a calculation into a complete result.

## Validation and remaining acceptance

See [the source qualification record](qa/synthetic-series-150-20261112/README.md).
The remaining issue scope includes the other three transforms, durable
checkpoint/restart qualification, pinned immutable replay inputs, indicator and
strategy adapters, full execution/resource scheduling, production deep paging,
multi-chart performance and native macOS/Windows save/exit/restart evidence.
Retained frontend algorithms remain offline migration oracles and the explicit
default-off legacy path; they are not a runtime fallback for enabled candidates.

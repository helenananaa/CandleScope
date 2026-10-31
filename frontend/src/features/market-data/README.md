# Market Data Feature

`market-data` owns the active K-line lifecycle for the current chart session:
initial history loading, bounded window stores, left-side pagination, backend
backfill completion, live K-line WebSocket updates, background interval warming,
and header price state.

## Public Contract

`useMarketDataRuntime` exposes:

```js
{
  view: { bars, seriesStore, meta, loading, error, lastPrice, dataSource, wsStatus },
  actions: { retry, loadMoreLeft, onVisibleRangeChange, consumeIndicatorRangeRequest },
  status: { hasMoreLeft, loadingMoreLeft, activeChartReady, indicatorRangeRequests },
}
```

The canonical chart data path is:

```text
shared REST/WS -> existing admission adapters -> MarketWindowSession.transact
  -> private SeriesWindowStore -> sealed commitState + delta -> read-only chart view
```

`SeriesDataFeed` is the only market-data path that should fetch K-line REST
history. Each mounted chart owns one `MarketWindowSession`, including its own
bounded windows for warm intervals. A workspace shares HTTP requests, stream
subscriptions and bounded copied seeds, never the active mutable window.
The session owns the private `SeriesWindowStore` and emits structural deltas (`replace`, `prepend`, `append`, `mid-merge`, `tick`). React `bars` stays
as a compatibility/read-model field; renderers should prefer `seriesStore` and
delta subscriptions for hot paths.

Session switches are optimistic: old bars may remain rendered while `meta.status`
is `loading`; the first warm-cache or REST result swaps the active store, while a
slow empty load may clear after the configured timeout.

The workspace `MarketDataManager` owns one `ForegroundPreloadGate`. Chart
foreground requests and busy owners use this same gate. Its `MarketWarmQueue`
accepts watchlist, hovered-product/interval and frequent-interval demand leases;
these consumers do not own candle arrays or independent network budgets. Normal
warming waits for the quiet dwell. A deliberate hover/focus after 150 ms can
skip that dwell, but cannot preempt foreground or active hydration. Speculative
work is cancellable, deduplicated by full series and target count, and limited
by pending jobs, source-row cost, estimated in-flight bytes and cooldown.

Each chart's `ChartMarketController` promotes an already running warm request
before the selection becomes busy, then releases its own hover lease. The
foreground viewport joins only matching work; hydration, repair and different
count/wait requirements keep their own contracts. Cancelling one chart never
releases another consumer's lease. Up to three available favorite/frequently
used intervals are ranked from bounded local usage metadata. Hovering never
changes selection, watchlist tiers or usage history.

Historical navigation explicitly permits cache reads. A before-page hit requires
verified closed coverage through the requested right boundary as well as the
requested row count; old rows alone cannot prove the gap. Right navigation uses
an already proven range, falling back to its existing strict repair read if the
proof is lost. Feed defaults, backfill/reconnect readback and strict repair still
require network. A new backfill completion revokes earlier instrument proofs.
Active windows retain their current ranges with O(1) bound observations; hard
pool limits win over retention. Capacity protects active series, rejects surplus
realtime admission without throwing into transport, and exposes the rejection
counter. Window rows remain privately owned throughout.

Cold activation is split into two contracts. The visible `viewport` request
asks for at most 500 bars (or the smaller derived-interval source budget) and
waits at most 1.5 seconds. Once that range is settled, an
`active_hydration` lane probes the full target of up to 1,500 bars with no
backend long-poll. It outranks ordinary preload but remains synchronously
preemptible by foreground work. Partial probes use snapshot mode and publish
nothing; only a complete, contiguous, final response performs one atomic
prepend so chart rows, indicator input, and validation metadata share the same
revision. A bounded 30-second probe round resumes with capped backoff until the
active session is complete or changes.

## Allowed Dependencies

- May consume the chart session view/actions/refs passed by the app composition
  root.
- May consume chart session transition events and reset its own K-line loading,
  error, and visible-data state for the active session.
- May use internal chart data and stream helpers from this feature directory.
- May call backend K-line services through `feed/SeriesDataFeed`.
- `MarketDataManager` owns shared K-line transport leases and immutable range
  cache admission. Charts and watchlist warming consume its service port.
- `manager/initialMarketRows` seeds a missing chart with bounded provisional
  shared rows. An existing chart window keeps its own navigation boundary.
- May publish indicator range request events when `prepend` or `mid-merge`
  expands the active window; indicators own the actual range request side
  effects.

## Forbidden Dependencies

- Do not own symbol, exchange, market type, interval selection, or user session
  preference persistence; those belong to `features/chart-session`.
- Do not compute or mutate indicators directly.
- Do not expose K-line reset setters back to chart-session or `App.jsx`.
- Do not call K-line REST services directly outside `feed/`.
- Do not own drawing, export, watchlist, settings, or alert UI state.
- Do not expose raw Lightweight Charts objects in the public contract.
- Do not introduce feature-owned candle arrays or bypass shared admission for
  watchlist/hover warming. The watchlist owns demand policy, not candle storage.

## Live window ownership (issue #123 P1)

`useChartDataRuntime` retains its existing loading/recovery adapters, but every
write adapter enters `MarketWindowSession.transact` with a captured selection
token. The owner rejects stale tokens, including A→B→A and unmounted charts.
Store writes and proof changes are sealed into one `commitState` before any
subscriber or deferred indicator callback runs. `commitRevision` also advances
for proof-only commits; `dataRevision` and `axisRevision` retain their original
meanings. Reentrant commits wait until the current publication completes.

Consumers receive `SeriesWindowView`, without write methods or writable identity.
Live readers protect array/row/time-set aliases and retain stable array/time-set
identity for hot ticks. `MarketWindowReader.capture()` copies a stable input for
asynchronous work; migrating every asynchronous projection to that API and
checking its revision before publication is a later phase.

Cache resource and lease keys include the window ID; request/stream keys keep the
canonical market-series identity so transport is still shared. Closing a chart
revokes writes immediately and releases only its windows/resources. The existing
shared HTTP coordinator cancels physical I/O only after the last consumer leaves.
The seed registry retains at most 64 series × 256 copied rows and provenance. A
seed does not confer validated history on another window.

The architecture check rejects direct mutable Store/legacy registry imports from
live components and market-data adapters, and restricts the commit authority to
the composition root. Offline replay/static sources retain their own owners and
consume the same source-neutral reader contract. No retired Pyne route is restored.

P1 does not replace history acceptance/recovery decisions or the scheduler. The
P0 native-restore tail catch-up and disconnect final-bar gaps remain P2 work.
Rollback is a revert of this change; persisted user-data formats are unchanged.

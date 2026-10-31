# Market snapshot/stream contract and healthy switching

Tracks #162, #160 and #163, on the shared admission boundary from #159.

## Authority and scope

The backend owns source quality, finality, calendar arithmetic, missing-history
detection and repair. The frontend validates format and full series identity,
orders comparable versions, retains coverage evidence, and decides whether a
consumer can reuse the retained data. Local receipt order is not a source version.

HTTP history/range/before/latest contract payloads and browser K-line events have
an additive `stream_version` object:

| Field | Meaning |
| --- | --- |
| `protocol: 1` | Contract version; missing/unknown versions cannot grant healthy reuse |
| `series` | Exchange, market, symbol, canonical interval and all seven semantic identity fields |
| `epoch` | Random identity of this server clock; not comparable across processes/restarts |
| `generation` | Monotonically assigned clock incarnation within the epoch; changes after eviction/invalidation |
| `sequence` | Per-series publication-attempt cursor |
| `barrier` | Per-series non-replaceable fact cursor: created, closed, amended and backfill-completed |
| `observed_at_ms` | Server observation time, not candle open time or browser receipt time |
| `stable` | HTTP only: whether the read crossed a critical publication or clock change |

The clock retains at most 4,096 full series identities. Eviction never resets a
series to an apparently comparable zero cursor. Query reads capture both ends of
the publication clock. A pending asynchronous publication prevents a stable
snapshot. Final-only history may cross coalesced forming updates when its critical
barrier is unchanged; it retains the starting cursor. A query containing forming
rows requires the whole clock to remain stable.

This is a publication/snapshot protocol, **not** a storage commit revision, a
source-priority ranking, or a durable replay cursor. Storage revision fences and
external-writer invalidation remain the separate D126 contract. Multiple backend
workers need sticky routing for healthy reuse; mismatched epochs fail closed.
Unannounced out-of-process changes are not magically observed by this clock.

## Cutover and recovery

1. Establish the stream lease and fetch a snapshot. Either may arrive first.
2. A stable snapshot establishes a baseline only for its current local connection
   generation. At least one actual matching bar event is required to link it to
   the live stream. An ACK/online status alone proves nothing about data.
3. Forming events may skip sequence values with the same barrier. A critical
   event must advance the barrier exactly once. Missing barriers, an incarnation
   change, disconnect or a backfill invalidation revoke continuity.
4. Older versions cannot overwrite newer accepted rows. An in-flight response
   from an obsolete incarnation is rejected; retired incarnations remain rejected
   (64 per physical connection, then an explicit reconnect is required). Legacy/unstable responses use the
   existing HTTP/WS request fence and remain provisional.
5. Recover through a fresh backend read. No proof from the previous connection
   may validate that recovery read. There is no claim of replay/resume support.

A snapshot whose barrier is newer than the last accepted stream/snapshot cursor
may cross a correction the client never received. It revokes older coverage and
indicator input stamps globally, then proves only the returned range. Unreturned
rows remain available as provisional display data.

K-line events carry `affected_range` in milliseconds and `previous_open_ms` from
the backend calendar. A continuous authoritative close can extend a retained
proof only when that predecessor equals the proof's right edge. A jumped forming
tail cannot invent missing bars. Automatic extension currently covers continuous
crypto calendars; other session calendars conservatively fall back to reads.
Backfill completion carries its affected range and version in the detail and
envelope. Unknown ranges invalidate the full retained proof. Known ranges split
coverage and invalidate intersecting indicator prefix/range stamps. Unrelated
historical coverage survives. Historical amendments do not refresh tail age.

## Cache decision and network execution

`SharedMarketCache.planHistory` owns the decision and exposes separate
`historyCovered`, `subscribed`, `continuous`, and `fresh` evidence. Freshness
requires a real tail event within 15 seconds by both receipt and server time
(at most five seconds of future clock skew). Coverage must reach the server's
expected closed predecessor; row count alone is insufficient.

A new chart that has received its interval ACK can reuse the shared owner's
current stream observation while waiting for its own first tick. It queries the
owner's existing expiry/continuity evidence; joining never renews its age. This
avoids an unnecessary one-second fallback tail read. History coverage is still
checked independently. A narrower complete snapshot merges overlapping valid
coverage instead of discarding the previously verified wider hydration range.

- Healthy and sufficient: return final history directly, retain the forming tail
  in the shared/private projection, and reuse the existing stream.
- History present but tail uncertain: render the bounded provisional preview,
  then verify with the backend. A subscription by itself cannot repair history.
- Missing history: load the requested window through the manager's shared broker.
- Explicit repair, strict range reads and default Feed requests remain network
  reads. Only initial viewport/hydration requests explicitly opt into healthy
  history reuse; historical navigation retains its existing range-proof policy.

When a workspace manager owns health, the private window's old freshness TTL
cannot bypass this decision. Each chart still owns its navigation boundary and
rebuildable window. A correction learned by another consumer patches only its
retained range through the existing owned publication path.

`MarketDataManager` executes shared HTTP requests, stream leases and recovery;
it does not own a second health policy. Verification coalesces by full series,
has at most two active/eight queued requests, a five-second per-series cooldown,
and at most 12 attempts/minute. Each read is bounded by the proven demand, capped
at 1,500 target bars. Failed/budgeted verification leaves data provisional; a
later real event or foreground request can retry. This is not a whole-provider
source-row throughput guarantee.

A batch transport reconnects its own socket while retaining logical leases.
Its socket close revokes continuity and ACK state, but does not dispose the
shared entry. The next open must reach the same consumers and resume admission;
new consumers join that recovered entry. Actual lease release remains terminal,
and the transport fences events from retired socket instances. Transports that
do not reconnect retain their existing terminal-close behavior.

## Demand and retention budgets

Active chart/watchlist leases retain their existing independent lifetimes.
The speculative live tier retains at most four series for at most 30 seconds:
hover before frequent periods before watchlist warming, then LRU within a tier.
It acquires the stream before the warm read, shares the existing physical stream,
and promotes a hover lease before pointer cleanup on selection. Cancellation of
unfinished speculation releases its lease; completed/promoted warming may remain
until the fixed expiry. Eviction/expiry releases only that speculative lease,
never another chart's subscription. There is no unbounded background reconnect.

The existing warm HTTP queue still bounds concurrent work, source rows and
estimated bytes. Shared data remains capped at 128 series, 200,000 rows overall,
and 30,000 rows/series. Verification and speculative metadata are bounded too.
Legacy servers continue rendering and loading through the old admission path;
they never take the new healthy-history shortcut.

## Validation routes

- `npm run check`: architecture, plugins, i18n, types, lint, frontend and desktop
  regression suites, production build.
- `npm run test:market-health:browser -- --out <receipt-directory>`: production
  minified Chromium fixture with the actual initial-load hook, Feed, private
  stores, shared manager and candle renderer; controlled transport.
- Add `--native` to the browser command to use an isolated Electron host; set
  `ELECTRON_PATH` when Electron is not installed in this checkout.
- Backend `tests/test_market_stream_version.py` plus API, batch-stream,
  DataManager/query, backfill and durable-delivery regression suites.

These establish the scoped source/browser behavior. They do not certify the
157-item acceptance matrix, live-provider soak, every session calendar, or an
installed/native release's save/full-exit/restart behavior.

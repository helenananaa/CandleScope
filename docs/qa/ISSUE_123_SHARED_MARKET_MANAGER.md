# Issue #123: shared market manager and bounded range cache

## Scope and baseline

This implementation follows the user's 2026-10-29 approval of a shared market
data pool, independent chart windows, unified consumer demands and bounded
speculative warming. The implementation baseline is main `ce07e1bf`; P1–P3,
including PR #140, have merged. Earlier issue text saying P3 is unmerged is
historical. No changes to exchange collection, trading, or retired Pyne support
are in scope.

The goal remains active until implementation, regression, actual dual-chart /
switch / hidden recovery acceptance, fixed-input comparison and PR/issue
publication are complete. A passing unit test is not native acceptance.

## Contracts to preserve

- Every HTTP, WS and repair response is admitted before consumers observe it.
  Source ordering is not inferred from receipt time or a local revision.
- The shared cache owns immutable market facts, range coverage, finality and
  revisions. Navigation, truncation and viewport ownership remain per chart.
- Ordinary live updates use a tail-sized path. Historical merges must not make
  every tick scan, sort or clone the entire cache.
- Cache hits are range/quality claims, not merely nonempty arrays. Insufficient
  proof may seed a display but never completes a repair or declares live data.
- A consumer releases only its own demand. Cancelling a switch or prefetch must
  not cancel a request/stream retained by another consumer.
- Snapshot acquisition and changes have a version boundary. Old selections may
  populate valid shared data but cannot publish to the new chart selection.
- Hidden charts keep accepting data; display scheduling remains independent.
- Indicator output depends on full series identity, definition/parameters,
  calculation origin/range and input versions. Corrections invalidate affected
  dependencies; stale async output cannot enter display or caches.
- Cache and speculative work have explicit budgets. Warming never changes user
  selection or persistent watchlist tiers. Active work takes precedence.
- The initial sharing scope is a frontend workspace. Native cross-window seeds
  retain their existing proof limitations; no cross-tab singleton is implied.

## Implementation sequence and status

1. **Implemented; broader validation pending:** shared immutable range-cache admission with HTTP/WS fences,
   bounded retention, range proof, versioned reads and regressions.
2. **In progress:** framework-independent MarketDataManager around existing shared
   transports; route production chart history, real-time and repair inputs
   through it; preserve private bounded window commits and recovery contracts.
3. **Pending:** unify consumer demand ownership with watchlist K-line warming;
   keep quote/indicator protocols and business ownership explicit. Migrate
   duplicate candle storage/acceptance rather than adding another writer.
4. **Pending:** chart switch orchestration, cache-first range acquisition and
   budgeted hover/favorite-interval warming with promotion/cancellation.
5. **Pending:** indicator dependency/range revisions and async output fencing;
   architecture enforcement and documentation.
6. **Pending:** full checks and fixed-corpus baseline/candidate measurement;
   actual dual-chart independent navigation, switch races, corrections,
   hidden/minimized reconnect, and bounded-memory observation. Publish a PR and
   issue evidence with remaining gaps separately identified.

## Required regressions / acceptance

| Boundary | Required observation |
| --- | --- |
| Shared admission | Invalid batch rejected atomically; late forming/HTTP cannot undo concurrent close/amendment; later legitimate repair remains possible |
| Cache identity | Provider/venue/market/interval/session/adjustment identities cannot collide |
| Cache coverage | Disjoint ranges, missing proof, partial/contradictory responses and eviction cannot manufacture completeness |
| Window isolation | A deep-history navigation and trim leaves B live; A return-live does not reset B; shared corrections reach matching retained ranges |
| Ownership | A→B→C with delayed results, closure, StrictMode and one-consumer abort do not publish into the wrong owner |
| Indicators | Historical changes invalidate affected outputs; unchanged ranges remain reusable; warmup/checkpoints and timestamps stay aligned |
| Warming | Hover cancellation, foreground promotion, request sharing, concurrency/byte budgets and persistent-tier independence |
| Scheduling | Data accepted while hidden; restore paints without requiring a new tick; no hidden RAF loop |
| Performance | Fixed corpus, same layout and observation protocol; capture admission/display latency, requests, connections, allocation/retention and final content |

## Evidence

Development checkpoint (not UI/native acceptance):

- The workspace now constructs `MarketDataManager`, with shared HTTP request
  ownership and one instrument subscription fanned out over the existing batch
  transport. Both physical HTTP and WS responses enter `SharedMarketCache`
  before delivery. Private window writers and recovery remain in place.
- Historical range cache hits require retained verified final coverage. Explicit
  repair/strict reads bypass the hit. Latest reads still contact the backend.
- Missing chart windows can paint provisional shared rows; this does not claim
  fresh history or complete recovery. Existing private navigation wins over a
  shared latest-tail seed. HTTP corrections patch only intersecting retained
  ranges through the existing owned commit; they cannot advance window edges.
- Found during integration: Feed was wrapping the manager in another request
  broker. The API now declares request-lease ownership, preserving one broker;
  production-injection regressions pass with batching enabled and disabled.
- 389 market-data tests passed before the window-binding addition. Subsequent
  regressions cover shared correction, stale owner, amendment recovery ordering
  and `repair=none` backfill readback. Existing Feed requests explicitly demand
  a network read; the server repair flag is not a frontend cache permission.
- The first development checkpoint passed full `npm run check` (architecture,
  plugin boundary, i18n, TypeScript, ESLint, frontend/desktop tests, production
  build). Log: `/tmp/issue-123-manager-checkpoint-check.log`. Existing large
  chunk warnings remain. This is a development check, not final-head acceptance;
  actual UI, native, performance and retention checks remain pending.
- The implementation plan was published and read back at issue comment
  `6494410381`. No PR, performance improvement, complete consumer migration or
  actual UI/native acceptance is claimed at this checkpoint.

Preserve failure samples and distinguish controlled fixture proof from live
exchange and packaged-native evidence. Watchlist storage/transport migration,
switch/hover orchestration, indicator dependency integration, full validation
and performance/retention acceptance remain outstanding.

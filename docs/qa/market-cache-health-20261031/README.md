# Healthy shared-cache switching — 2026-10-31

Base: merged #159, `4bf08e69342b6a9aeece91a9a44991030e1f0b9d`.
The [source manifest](source-manifest.json) hashes the changed frontend/backend
files used by the receipts. The [contract](../../architecture/MARKET_CACHE_HEALTH.md)
defines the authority, cutover, invalidation, compatibility and resource budgets.

## Observed behavior

Both [Chromium](chromium.json) and [Electron 43.3.0](electron.json) run the
production-minified fixture with real React, `useChartInitialLoad`, `SeriesDataFeed`,
the shared manager, independent `SeriesWindowStore`s and the candle renderer.
Only the market transport is controlled. Each run proves:

- Two BTC charts share one initial history request and physical stream.
- ETH warms with 500 final rows and receives a real versioned forming event.
- Clicking ETH in chart A makes **zero additional HTTP requests and zero physical
  subscriptions**. It publishes 500 closed rows plus the forming tail. Chart B's
  rows remain exactly unchanged.
- A skipped critical barrier triggers exactly one coalesced history read. A
  historical correction from that read reaches the actual retained candle window.
- Owned streams close on cleanup; zero remaining Workers and zero runtime
  exceptions are reported; the owned browser/native process exits successfully.

Releasing a speculative stream revokes live health without cancelling a chart's
independent shared HTTP lease. The existing watchlist cancellation regression
exposed this boundary during final verification and passes after the fix.

The default speculative tier has four series and a 30-second hard lifetime.
Focused regressions cover priority/eviction, cancellation and promotion, other
consumer leases, coverage extension, missing barriers, stale/duplicate versions,
retired epochs, disconnect fences, legacy fallback after reconnect, freshness
expiry, negative ACKs and targeted indicator-input invalidation. Verification IO
is bounded to two active/eight pending reads and 12 attempts/minute.

## Checks

- Full `npm run check`: architecture/plugin/i18n checks, types, lint, frontend
  regression suite, isolated drawing-performance gate, desktop tests and build.
- Backend API/version/batch-stream suite: **112 passing tests**; the broader DataManager/query/cache,
  backfill and durable-delivery suite. The latter has **306 passing tests**;
  these suites partly overlap and their counts should not be added as unique tests.
- Eight focused backend version tests include real DataManager query/event-bus
  wiring, calendar predecessor serialization, publication races, bounded clock
  reincarnation and explicit cache invalidation/clear.
- The macOS package workflow now runs the new protocol test and K-line HTTP,
  event-envelope and batch-stream regression files with bundled Python.

Existing pane-cleanup lint and bundle-size warnings remain. No new lint warning
is waived. Browser fixtures stay inside the chart-adapter test boundary.

## #159 review disposition

The review found a stale browser assertion: the indicator cache now includes the
provided-input signature, while the browser fixture queried the old key. Commit
`49d6c76a` fixes the assertion wiring and keeps hidden/late-result isolation checks.
Full local checks and the unchanged browser rerun pass. One earlier browser run
observed an empty-URL detached Worker beyond the harness cleanup deadline; the
repeat had zero remaining Workers and no runtime exceptions. This is retained as
a harness observation rather than a claim of deterministic cleanup under load.

No remaining production merge blocker was found in the reviewed shared-manager
change. Both architectures passed [workflow 41172222665](https://github.com/helenananaa/CandleScope/actions/runs/41172222665)
at the reviewed head, including packaging, bundled regressions, relocated-runtime
verification and launch/restart, before #159 was merged.

## Evidence limits

The new Electron evidence is an **isolated native host with controlled transport**,
not an installed CandleScope package's saved-workspace/full-exit/restart acceptance.
The prior #159 package checks do not automatically qualify this follow-up change.
Live-provider soak, every session calendar, external storage writers and the
157-item acceptance matrix are not certified here. Unknown protocol/identity
mismatches fail closed; legacy servers render without healthy-history reuse.

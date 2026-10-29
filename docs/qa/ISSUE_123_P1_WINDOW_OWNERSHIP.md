# Issue #123 P1: independent live windows and one commit owner

Date: 2026-10-28. Base: `b84b5e3d514e43fca556613fe107e29d12f7a329`.
Implementation: `f52c29e4a8de3aeb00c6a1acd1853998a9772f7a`.
Scope: live chart window ownership, read contract and commit publication. No
persisted-data migration, transport replacement or retired Pyne support.

## Ownership and migration

| State / capability | Owner after P1 | Shared boundary |
| --- | --- | --- |
| Active and warm bounded windows; trim/right edge | One `MarketWindowSession` per mounted chart | Never shared between chart cells |
| Data/proof commit and revisions | Session transaction, captured selection token | Read-only `SeriesWindowView` / `commitState` |
| Compatible HTTP and WS I/O | Existing workspace coordinators | Canonical series identity, independent consumer leases |
| Warm seed | Workspace registry; <=64 series ×256 copied rows | Provenance retained; local history proof starts unvalidated |
| Cache accounting and eviction | Existing cache registry, window-scoped keys | No sibling-window victim or active lease collision |
| Domain admission/recovery | Existing adapters in P1 | Policy/recovery extraction remains P2 |
| Offline replay/static chart | Existing source-specific owners | Source-neutral read contract |

Every exported write adapter in `useChartDataRuntime` enters the owner: set cache,
merge cache, patch cache tick, activate cached window, detach, replace, clear,
transition, merge commit, forward commit, tick commit and trim. Delayed warm
publication also checks the captured token. All live Store mutations are private
typed commands. Publication seals data/proof/revisions for all affected windows
before subscribers and deferred callbacks, and queues reentrant work. An adapter
exception invalidates proof instead of publishing inherited success.

The reader exposes no mutable Store or identity setter. Live arrays and time-set
views retain identity, rows reject mutation, and `capture()` provides stable
async input. This change does not migrate every async indicator to capture plus
late-result rejection; that remains part of the later pipeline work.

## Regression evidence

The old registry reproduced the defect: with a three-row limit, A prepending
`[60,120]` changed B from `[180,240,300]` to `[60,120,180]`. The new regression
keeps B unchanged, then tests B's tick/replace and A's disposal independently.
Additional tests cover one shared HTTP request with A cancelled and B surviving,
ABA token rejection, StrictMode reacquisition, seed ownership/provenance,
proof-only revision, coherent notification, reentrant commits, immutable aliases
and stable time-set identity. Architecture fixtures reject live writer bypasses.

Final locked-dependency `npm run check`: 4,440 frontend tests plus the separately
run performance worker test; 123 desktop tests; architecture/plugins/i18n/
typecheck/lint/build passed. This includes seven new owner regression tests and
23 architecture fixtures, plus the existing registry/transport/recovery checks.

## Runtime and performance evidence

Paired measurement uses the base and candidate production bundles, both rebuilt
with the exact lockfile (React 19.2.4, Lightweight Charts 5.1.0, Vite 7.3.6),
Electron 43.3.0, Apple M1 / 16 GiB / macOS 26.6.2, 1280×800 DIP, no indicators
or drawings, sidebar collapsed, 1,500 rows/window and a 10,000-row limit. Each
layout runs one warmup then five measured runs of 200 forming updates at a target
50 ms interval. No builds/tests run during these measurements. The initial
shared node_modules had drifted; those preliminary runs are excluded.

Frozen corpus SHA-256:
`aec184aa14a607d149bd0b0e1e2d31a58924538c00a764435d78ec990e6eb1f3`.

| WS receive → observer notification / two subsequent rAF, P95 | Base | P1 |
| --- | ---: | ---: |
| Single chart | 16.3 / 49.2 ms | 16.5 / 49.4 ms |
| Dual, first/focused window | 14.6 / 47.4 ms | 14.3 / 46.9 ms |
| Dual, independent secondary window | No independent Store observation | 47.5 / 81.0 ms |

Each row has 1,000 measured input samples. The first/focused notifications meet
the P0 21/20 ms and 62/61 ms comparison budgets. The secondary retains the
existing visible-secondary scheduling delay: its result is a separately reported
P3 input, not evidence that both windows satisfy the old shared-first-Store
budget. Two rAF callbacks do not measure GPU completion.

Both versions: single/dual candleSeries.update counts 1,000/2,000; no setData,
extra Kline HTTP, chart.data.commit or observed long tasks during measured tick
intervals; one physical WS, one/two logical consumers. The candidate produced
1,000 notifications for each independent dual Store without losing inputs.

Five fresh Node processes, 20 retained stores/windows each, forced GC:

| Retained bytes per store/window (median) | Base Store | P1 owner + reader | P0 budget |
| --- | ---: | ---: | ---: |
| 1,500 rows | 363,341 | 449,693 (+23.8%) | 453,904 |
| 10,000 rows | 2,882,522 | 2,968,847 (+3.0%) | 3,603,145 |

The 1,500-row comparison has little budget headroom. This fixture has basic OHLCV
rows and amortizes one shared seed registry over 20 windows; richer fields and
other window counts are not covered by that number. Runtime heap samples were
not forced-GC: base single/dual maxima 107.3/111.6 MB, P1 52.0/120.4 MB. These
are diagnostic samples, not retained-heap savings or a leak claim.

External instrumentation reads Store/lifecycle/performance events; layout,
navigation and lifecycle changes use the actual UI. No application state is
assigned through the instrumentation. Final browser/native evidence:

| Actual UI scenario | Observed result |
| --- | --- |
| Same BTCUSDT 1m independent cells; A drags to capacity | A 10,000 rows, right-truncated; B retains the original 1,500 rows, revision and viewport |
| B receives six new bars while A stays historical | B 1,506 rows; A retains its original head/tail |
| Browser hidden for 48,584 ms, two more bars and historical amendment | Both overlapping windows receive the authoritative amendments; B reaches 1,508 on restore; A retains its historical bounds |
| B also trims to capacity, then explicit return to latest | B replaces its window with 2,000 rows (1,500 restore plus 500 viewport preload); A rows/revision unchanged |
| Close A, then append plus 20 forming inputs | B reaches 2,001 rows; logical WS subscribers 2→1; physical WS remains one with unchanged open/close counts |
| Repeat B restore and inspect settled viewport, then trim A again | B's visible range contains the latest timestamp and is unchanged by A's second capacity trim |
| Final authoritative row comparison | All 12,000 retained rows match OHLCV/is_closed; distinct readers and coherent commit revisions |
| Native minimize for 63,416 ms | Closed bars and overlapping amendment accepted by both owners; latest forming tail remains absent while minimized |
| Native restore without a new tick | Focused A catches up during the sample; secondary B still lacks the latest forming row 28.6 s after restore. New ticks then update both. F1 remains open |
| Quit/relaunch isolated native profile | BTCUSDT 1m, independent groups and dual layout preserved; two fresh readers render the current source tail; one physical WS |

Viewport scrolling after a restore is asynchronous. The first post-click
screenshot was transitional; the settled range is separately captured in
`12-settled-viewport.json` and `13-final-viewport.json`. Browser capacity drags
are not claimed as native continuous-drag coverage. The native run loads a
production frontend bundle in the desktop host; it is not an installed-release
acceptance run.

## Limits and rollback

P0 F1 (native restore without a new tick does not proactively catch up dirty tail)
and F2 (offline old-forming final value outside latest-two recovery) are P2 defects,
not fixed or reclassified by this change. Real-network cold P95, sleep/wake,
long-duration allocation, all async indicators, repair interleavings and installed
release acceptance are not implied by these fixed-input samples.

Revert this PR to roll back the ownership change. There is no persisted schema
change. Keep the original P0 evidence and the P1 paired baseline when reverting.

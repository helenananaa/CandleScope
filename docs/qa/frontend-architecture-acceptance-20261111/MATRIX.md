# Frontend architecture acceptance matrix

The frozen requirements are in `requirements.json`. This run covers #123 and
the bounded #160/#161/#163/#164 follow-ups. #154's new worker/state/SDK choices
remain a separate, explicitly deferred optimization decision.

Evidence is recorded per layer. A component or controlled-browser result does
not certify the installed app. macOS and Windows remain separate dispositions.
The native run uses an isolated profile and a relocated, signed current-source
macOS arm64 package. The existing user installation/profile is unchanged.

## Entry and owner audit (#163)

| Entry | Cache / transport owner | Consumer / lease owner | Intentional exception |
| --- | --- | --- | --- |
| First history / selection | `MarketDataManager.fetchKlinesHistory` → health/coverage check → shared request coordinator → `acceptHttp` → shared facts | Each chart's `MarketWindowSession` and feed generation; independent output window | Explicit `network-only` and recovery reads must bypass old cache |
| Latest / polling | Manager → shared latest coordinator → `acceptHttp` | Each calling window/feed; physical request survives one consumer's release | Latest is a fresh tail validation, not proof that the prior cache is current; a healthy selection can bypass this path |
| Range / repair readback | Manager range cache/proof check → shared coordinator → `acceptHttp` with storage-revision floor | Range/repair generation plus window owner | Version-floor / correction readback must reach authoritative backend storage |
| Before / left pagination | Manager before cache/proof check → shared coordinator → `acceptHttp` | Feed's fixed `before`, request generation and independent window | Partial/unknown coverage cannot advance the original page boundary |
| Realtime / cancellation | Manager-owned shared logical streams and underlying batch transport; facts admitted before fan-out | Independent logical leases; only final consumer closes physical work | ACK alone certifies neither freshness nor continuity |
| Disconnect / resync | Health invalidation and bounded `MarketHealthRecovery`, shared authoritative readback | Source generation + current consumer demand | Display pauses cannot discard confirmed/revision/control events |
| Watchlist | Injected `MarketDataService`; full tier shares manager requests/streams | Watchlist demand lease, separate quote contract | Quotes and full K-line subscriptions have distinct business semantics |
| Indicator input/output | `IndicatorDataManager.inputs` / `results`; hosted protocol owners remain distinct | Definition, input range/origin/version, task epoch and private script session where required | Forming previews and window-relative JS do not become durable/full-history strategy state |
| Replay/frozen/result view | Their own source authority, common read/chart contracts | Replay cursor/run/dataset identity | Offline or revealed-only data must not start live exchange requests |

Architecture checks and the production-adapter concurrency tests enforce this
audit; it is not based only on matching facade names. Relevant tests include
`seriesDataFeedConcurrency`, `marketDataManager`, `sharedMarketCache`,
`sharedKlineRequestCoordinator`, `batchKlineStreamCoordinator`,
`marketDataWorkspaceLifecycle`, `chartDataFlowManager`, `indicatorResultManager`
and `apiPayloadParsers`.

## Requirement groups and evidence

| Group | Required observations | Evidence route |
| --- | --- | --- |
| Independent windows | Same series, A left pagination through 10,000-bar capacity trimming, B remains live; A restore/close does not change B's retained range or lease | Native raw windows/screenshots/transport counts; controlled React/window regressions |
| Admission / proof | Bad OHLCV rejected with reasons, legal negative prices/volume semantics preserved; endpoint missing/unknown/contradictory proof handled distinctly | Current parser/quality/feed component tests; controlled browser health/correction path |
| Races / versions | Cold history versus realtime, late HTTP, old selection/repair/frames, amendment/finality conflicts; no stale overwrite | Controlled market-health fixture, actual Pine HTTP/WS/SQLite fixture, source regressions |
| Atomic publication | Data/proof/version belong to one commit; immutable async inputs and task/definition/origin checks | Window/stable snapshot/result ingress regressions; installed numerical oracles |
| Pagination / unavailable | Fixed before boundary; partial, empty, exhausted, unavailable, rate-limited results do not skip pages or retry without bounds | Feed/right-window/recovery tests; installed deep-history traversal |
| Cache health / selection | Coverage, continuity and freshness separate; insufficient tail/history validated; budget-denied warming; healthy compatible target avoids duplicate reads/physical streams | Controlled health fixture; native cold/hot request and socket receipts |
| Common indicator results | Builtin, JS, Pine, Python keep their runtime/origin/session contracts; compatible requests share; edits/revisions/cancellation invalidate safely | Adapter matrix from #356, result tests, native four-runtime visible-range numerical oracle and restart |
| Hidden / disconnect | Actual OS minimize, renderer disconnect, false-live prevention, recovered rows/values/viewport, bounded hidden frames | Native minimize/network receipt plus controlled no-new-tick restore/correction fixture |
| Resource lifetime | Two-chart run ≥30 minutes, ten close/recreate/switch cycles, input leases/queues/cache budgets, process RSS/CPU and main-heap samples | Native elapsed wall clock, process trees, broker counters, per-cycle oracle |
| Tail rendering / cost | Incremental tail path retained; structural rebuilds identified; timings/long tasks and request/connection counts reported without invented P95 targets | Existing renderer/scheduler tests; native observer and phase samples |
| Save / exit / restart | Saved selection/layout/scripts/parameters; all owned processes exit; new app process reestablishes correct sessions and outputs | Relocated installed app, same profile, process-tree exit evidence and restored numerical oracle |
| Source boundaries / rollback | Offline revealed inputs do not leak future/live data; no simultaneous writers or obsolete language runtime | Revealed replay browser suite, architecture checks and explicit retired-entry rejection; historic rollback receipts kept separate |
| Cross-platform | Current package/source identity and platform-specific exit/restart | macOS run in this directory; Windows connectivity/qualification recorded independently |

## Measurement interpretation

Cold means a newly created frontend pool on the same machine/profile. Persistent
backend history is retained, so it is not labelled a cold whole-network download.
The default first launch is a setup/smoke case if it restores an interval outside
the BTC/ETH × 1m/5m matrix. Healthy hot trials record the health decision before
switching and the target's actual HTTP/physical-stream deltas.

Visible-bar time means loaded chart data with a mounted canvas, not GPU scanout.
Tail-ready time requires coverage, continuity and a real current source event;
neither an ACK nor a visible cached chart is enough. Timing includes the actual
startup/transport environment; no unmeasured performance budget is invented.

The process-tree RSS sum includes shared pages and is not unique physical RAM.
Main-renderer heap excludes other renderers/workers/backend heaps. Long-task and
mark observations have bounded storage. Counters/bounds and cleanup prove their
recorded scopes; a single 30-minute run is not an unlimited endurance guarantee.

Final outcomes, failures, repairs and remaining platform gaps belong in the
run report and machine-readable receipt. Unfinished rows are not silently
checked off from prior revisions or old warm-library/package evidence.

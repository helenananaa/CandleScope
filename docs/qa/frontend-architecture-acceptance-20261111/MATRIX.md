# Frontend architecture acceptance matrix

The frozen requirements are in `requirements.json`. This run examines #123 and
the bounded #160/#161/#163/#164 follow-ups. #154's new worker/state/SDK choices
remain a separate, explicitly deferred optimization decision.

Evidence is recorded per layer. A component or controlled-browser result does
not certify the installed app. macOS and Windows remain separate dispositions.
The native run uses an isolated profile and a relocated, signed current-source
macOS arm64 package. The existing user installation/profile is unchanged.

## Final evidence disposition

See [README.md](README.md) and [validation.json](validation.json) for the exact
revision of each check. The production candidate is `5c1a3cab6`; frontend and
indicator-runtime evidence from unchanged layers is explicitly reused. The
`77358341a` native core completed its 30-minute and restart subphases, but its
full receipt remains failed at the subsequent OKX deadline. Final targeted
Binance/OKX source recovery plus restart passes independently. Warm-data renderer
rollback passes with the same current backend/runtime; unprepared baseline
startup timed out. Neither old-backend downgrade nor cold rollback is certified.
The ten healthy native hot switches cover BTC/ETH 1m only; cold/runtime checks
also cover 5m. Windows and the broader #123 performance/scale/platform matrix
remain unqualified. No issue is automatically closed.

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

Cold means a newly created frontend pool after an actual renderer reload on
the same machine/profile. The backend process/catalog/history stay running; it
is not labelled a whole-app or whole-network cold start. Earlier whole-app
restart attempts, including their external metadata/stream timeout failures,
remain separately labelled and do not supply successful switch counts. The
final native save/exit/restart and sequential renderer rollback are separate
whole-app process-tree checks.
The default first launch is a setup/smoke case if it restores an interval outside
the BTC/ETH × 1m/5m matrix. Healthy hot trials record the health decision before
switching and the target's actual HTTP/physical-stream deltas.

Final cold/hot visible-bar observation requires matching requested identity, an actual Lightweight Charts candle with matching OHLC, and overlap with the reported visible time range. It does not measure GPU scanout. Earlier failed receipts used the weaker loaded-window observation and remain separately labelled.
Tail-ready time requires coverage, continuity and a real current source event;
neither an ACK nor a visible cached chart is enough. The control driver polls at 200 ms; switch timing includes command/inspection
round trips and is not isolated click-to-render latency. Timing includes the actual
startup/transport environment; no unmeasured performance budget is invented.

The process-tree RSS sum includes shared pages and is not unique physical RAM.
Main-renderer heap excludes other renderers/workers/backend heaps. Long-task and
mark observations have bounded storage. Counters/bounds and cleanup prove their
recorded scopes; a single 30-minute run is not an unlimited endurance guarantee.

Final outcomes, failures, repairs and remaining platform gaps belong in the
run report and machine-readable receipt. Unfinished rows are not silently
checked off from prior revisions or old warm-library/package evidence.

## Entry-specific regression index

These named cases are part of the final full frontend check; the installed
receipt supplies the separate user-flow evidence. Repair/version-floor reads
intentionally reach authoritative storage even when ordinary navigation hits
cached coverage. Latest freshness checks intentionally use the network; a
previous latest response alone does not establish current source health.

| Entry | Cache/proof and failure coverage | Sharing/cancellation/lifetime coverage |
| --- | --- | --- |
| History / first load | `marketDataManager`: promoted viewport warming, distinct count/intent/repair demand; `useChartInitialLoad`: pending retry retains its original indicator owner | `sharedKlineRequestCoordinator`: exact history requests join; distinct bounded batch; one abort, final abort, late abandoned completion; `seriesDataFeedConcurrency`: scheduler admission and per-Cell epoch/reconciliation |
| Latest | `sharedKlineRequestCoordinator`: latest repair policy and demand generation remain part of identity; health fixture requires current continuity/freshness instead of ACK | `seriesDataFeedConcurrency`: production HTTP adapter table covers shared fetch with caller-local abort/source/commit; final release retracts admission |
| Range | `marketDataManager`: bounded proven range hits, partial/contradictory proof requires read, correction readback bypasses cache | `seriesDataFeedConcurrency`: shared range retains independent page limits and indicator owners; one caller's commit failure does not reject another |
| Before / left | `marketDataManager`: proven before pages hit shared coverage, unknown right boundary/recovery reaches network; Feed tests preserve pending page boundary | Shared coordinator and production adapter cover independent caller cancellation and demand owners; native 10,000-bar trim preserves sibling's window |
| Realtime / cancel | `marketDataManager`: inactive intervals reject queued old frames; concurrent WS amendments reconcile with HTTP; reconnect preserves live leases | Two chart demands share admission/stream; closing one retains the other; batch coordinator retries transient logical failure and cancels final retry; late subscribers get current open lifecycle |
| Disconnect / repair | New completion revokes old proof before validation; Feed readback with `repair=none` still reaches storage; browser health/owner/correction cases | Native minimize/disconnect/reconnect and bounded shared recovery; workspace StrictMode replay, replacement, duplicate cleanup and stale microtasks release each generation exactly once |

The targeted native-repair suite adds a real SQLite/engine interleaving: a live
tail append during the single-slot 1m/5m/1h REST fetch. The write must succeed for
a disjoint native range, and still fail on a changed/deleted captured range.
This supplements frontend health proof; it does not weaken health criteria.

# Frontend architecture acceptance — 2026-11-11

This directory supplements the common indicator-result delivery in
[the adapter matrix](../indicator-results-161-164-20261111/README.md).
The frozen issue requirements are in `requirements.json`; entry/owner and
measurement definitions are in [MATRIX.md](MATRIX.md).

## Final disposition — 2026-11-12

Production candidate: `5c1a3cab6c61c8f8f7b78085db8cb211e784c056`;
base: `12514a92fb4cc8745e3564538dd68247316e019d`.
The #164 common result ingress and #161 supported-runtime adapters are delivered.
Acceptance found and repaired the 17 concrete defects below. The bounded local
checks are complete; this does **not** close all of #123's broader qualification.
No GitHub issue is closed by this report.

As requested, repairs receive affected incremental tests. Unchanged frontend
and indicator-runtime evidence is reused with its original SHA. There is no new
full-suite or 30-minute run at the final backfill-only commit. Machine-readable
provenance and limits are in [validation.json](validation.json); every archived
file has a byte count and SHA-256 in [evidence-index.json](evidence-index.json).

| Evidence | Revision / outcome |
| --- | --- |
| Frontend functional / performance / desktop | `8defe72d4`: 5087 + 1 + 134 passed; frontend unchanged through final candidate. Whole-repo lint at `8d5881340`, subsequent changed files linted. |
| Closed-only actual Python runtime / stream adapter | `77358341a`: 93 affected tests passed; adapter unchanged through final candidate. |
| Final canonical identity / backfill / storage / API / stream | `5c1a3cab6`: six new regressions fail before repair; 62 focused and 380 expanded tests pass afterward. |
| Native core / endurance / restart | `77358341a`: completed subphases below. Original full receipt remains **failed** at its subsequent OKX startup deadline. |
| Final source recovery and restart | `5c1a3cab6`: two sequential app launches; Binance + OKX each prove 500-row healthy reuse and 60 actual closed points per runtime per chart; configuration equality and full process exit pass. |
| Warm-data renderer rollback | `5c1a3cab6` backend/runtime; sequential current → baseline frontend `12514a92f` → current. All 15 steps pass; scripts/parameters/layout, four-runtime values, two logical streams over one batch socket and process exits pass. All 10133 backend/runtime files match. |
| Unprepared baseline launch | **Failed** at indicator-ready timeout; retained separately. Warm-data success does not qualify cold rollback or an old-backend downgrade. |

### Native measurements and retained failure

The [core summary](native-core-77358341a-summary.json) records 10 cold renderer
pools, 10 healthy BTC/ETH **1m** hot switches, 10,000-bar trim/isolation, actual
Return to realtime and product round trip, BTC/ETH × 1m/5m four-runtime math,
retired-Pyne rejection, native minimize plus 75-second renderer disconnection,
30 minutes (1,800,330 ms) with 10 switch/close/copy cycles, and save/full-exit/
same-profile restart. The unchanged frontend/runtime layers retain this evidence.
The later source step timed out with OKX pending; the full original receipt is
never relabelled successful. Final source/restart checks pass independently.

Cold visible bars: 434–889 ms (median 840); tail health: 5,355–13,756 ms
(median 8,577.5). Healthy hot observations: 732–782 ms (median 742), zero target
K-line reads and zero new physical K-line sockets across the ten 1m trials.
The 200 ms polling driver includes control/inspection overhead; these are not
click-to-GPU latency or a P95/SLA result. The hot trials do not claim a complete
1m/5m Cartesian matrix.

Across 53 resource samples, summed process-tree RSS was 2,497.7 → 1,326.2 MiB,
with a **4,295.4 MiB peak**. Shared pages are counted repeatedly; neither unique
physical memory nor retained-leak attribution is established. Main-renderer
used heap was 57.2 → 87.8 MiB (peak 108.3). Market cache held 15,131–15,167
bars (cap 200,000); input/result subscriber counts stayed two each. Completed
JS cache peaked at 24 entries and 4,150,963 encoded bytes (caps 80 / 4,194,304).
A read-only check around minute 29.5 verified the last 60 closed points of all
four runtimes on both actual charts; configuration was sampled after cycle ten.
These bounded samples do not establish continuous unsampled health or a full
allocation/GC profile.

Key receipts (gzip JSON):

- [Original native run, including its OKX failure](native-77358341a-okx-pending-acceptance.json.gz)
- [Final source/restart pass](native-final-5c1a3cab6-source-restart-acceptance.json.gz)
- [Final warm-data rollback pass](rollback-final-5c1a3cab6-warm-acceptance.json.gz)
- [Unprepared baseline failure](rollback-final-5c1a3cab6-unprepared-failed-acceptance.json.gz)
- [Current package/source manifest](native-final-5c1a3cab6-package-source-package-manifest.json.gz)
- [Rollback renderer/backend provenance](rollback-final-5c1a3cab6-renderer-manifest.json.gz)

The final current and composite-baseline packages also passed post-run signature,
bundled-runtime/dependency and relocated-path verification. They are local ad-hoc
arm64 packages launched with automation `--no-sandbox`, not notarization or
public distribution security qualification. Both use only the isolated QA profile;
the ordinary installed app and user profile are untouched.

## Repairs discovered during acceptance

1. **Binance stream connection:** the pinned CCXT default used port 9443.
   Independent live probes observed a connection reset there and real candle
   data on the official equivalent 443 endpoint. Both the strict spot profile
   and generic public spot WebSocket client now use 443. Derivative/test routes
   and proxy binding remain covered by regression tests.
2. **Shared market bootstrap:** a healthy ~18 MB spot catalog download could
   exceed CCXT's 10-second timeout, blocking dependent streams/history work.
   Binance spot public clients now have a bounded timeout of at least 30 seconds,
   respecting a larger configured ingestion HTTP timeout. This is a client I/O
   timeout, including later requests; request admission/cancellation still apply.
3. **Cold-load indicator owner:** a zero-wait history probe and its 1500 ms
   retry acquired different indicator-window owners. A completed retry could
   leave the probe's owner pending indefinitely, blocking builtin/Pine/Python
   on a secondary chart while its candles and JS result were visible. Retries
   now retain the original viewport owner. The real React + Feed browser fixture
   fails before the fix and passes afterward; no completeness proof is relaxed.
4. **Performance timeline retention:** the local event ring was bounded but
   repeated native Performance marks/measures accumulated. Each repeated name
   now retains its latest timeline entry. A real PerformanceObserver still sees
   every event: 5000 computations produce 10000 observed marks while retained
   entries stay one per name and the report ring stays at 240 events.

5. **Shared result publication:** a sibling could commit compatible builtin
   coverage to the common cache, while a mounted view retained a partial private
   projection. The scheduler then correctly skipped duplicate transport work,
   but the view never consumed that cache generation. Live runtimes now subscribe
   to matching result commits and use the existing deferred, lifecycle-fenced
   cache hydration scheduler. Matching shared definitions update together;
   private hosted-script projections retain their own keys. A real two-React-view
   fixture fails before the repair and passes afterward, without another range
   request, wire snapshot or viewport change; unmount releases result listeners.

6. **Native repair starvation:** a genuine missing ETH 1m closed candle was
   selected into the source journal, but all three projection writes conflicted
   with unrelated live tail revisions. The job then waited 15 minutes. Trusted
   Binance spot native repairs now capture a bounded pre-fetch range view:
   disjoint live updates may continue, while changed range contents, deletion
   watermarks, custom/foreign identities, derived outputs and oversized work
   retain their existing rejection rules. Three real-engine SQLite/transport
   interleaving regressions fail before the fix and pass afterward; all 43 range
   fence cases, 215 affected backfill/transport/derived cases and 61 revision
   admission/source cases pass. The failed installed receipt is retained.

7. **Quote lifecycle routing:** native startup diagnostics exposed eight
   middleware exceptions when watchlist price subscriptions began. Their
   `price` lifecycle key was incorrectly resolved as a candle interval. Price
   lifecycle now bypasses candle continuity annotation; its own subscription
   delivery stays unchanged. The real DataManager quote-lifecycle regression
   fails before the fix; 103 quote and source-continuity cases pass afterward.

8. **Backfill completion ownership:** a completed range that covered a pending
   initial window could clear loading through a newly generated range owner,
   leaving the initial owner behind. ETH 1m then displayed candles and JS but
   permanently gated builtin/Pine/Python. Full-window completion now retains
   the original initial owner. When the initial range is unknown, a child range
   cannot replace full count-back verification. Both real Feed/buffer cases fail
   before the fix; 102 affected cases and a real React browser completion case
   pass afterward. The failed installed four-runtime receipt and gate/cache
   diagnostics remain retained.

9. **Exact-repair ownership:** an authoritative external readback could remove
   a completed exact repair without releasing the range's deferred indicator
   owner. Native restart samples showed empty repair maps while both charts
   retained range owners and hosted/builtin results stopped. Each exact repair
   now keeps one owner across attempts and releases it only for a current-epoch,
   active-series, fully proven range. Capped children require aggregate finality;
   an unproven parent keeps its gate until full external verification. Both
   new real Feed/buffer regressions fail before repair and 104 affected cases
   pass afterward. The native failing ownership samples are retained separately.

10. **Recovery admission:** a real cold selection retained a missing closed
   ETH candle for 298 seconds while bounded health verification repeatedly
   issued zero-wait viewport requests. The backend intentionally makes those
   first-paint probes read-only, so this queue could not request the repair it
   needed. Recovery now uses the existing 1500 ms bounded viewport repair lane;
   concurrency, rate limits, cancellation and proof admission remain unchanged.
   A production-manager regression fails before repair and passes afterward;
   actual FastAPI/DataManager tests separately verify zero-wait versus bounded
   repair admission. The superseded installed run completed ten cold/hot trials
   but was deliberately stopped during its first soak cycle for this repair.

11. **Full demanded-history recovery:** a later amendment revoked historical
   proof; a narrow latest read restored continuity and proved only the last two
   rows. The health executor checked only that tail, leaving the existing
   1500-row demand permanently unverified despite intact durable rows. It now
   checks the demanded retained range using the existing binary time index and
   at most 128 proof records, without copying/scanning a history snapshot per
   tick. The failed native hot-setup receipt and proof diagnostics are retained.
   A focused source regression fails before repair and passes afterward.

12. **JS startup versus execution:** the installed simple close-times-two
   script reported an execution timeout. Its two-second clock started before
   the isolation iframe and Worker existed. A real Chromium regression delays
   trusted document startup by 2.2 seconds and fails before repair. The trusted
   bootstrap now gates user-source dispatch on a ready/run handshake: startup
   has its own bounded ten-second deadline, then user execution still has two
   seconds. Infinite loops, forged-ready messages, cancellation and cleanup
   remain checked. This source reproduction identifies a deadline bug; it does
   not retrospectively time the failed native worker's startup.

13. **Private and partial result publication:** after an input-prefix
   invalidation, the next admitted range can be the only resident cache output.
   The producing private session already merged that wire range correctly, but
   deferred cache hydration then replaced its whole history with one point.
   A real React/controlled hosted-stream regression reproduces this before the
   fix. Private sessions now retain their own wire publication path and are
   excluded from shared hydration; shared hosted results apply computed ranges
   while preserving outside history, including resolved empty ranges. Deferred
   auxiliary output updates preserve other indicators; shared point updates
   retain their existing incremental stream path. New-context resets and
   provided-window snapshots still replace their old output.

14. **Return-to-realtime intent:** review of the completed `7cbdd1a6f` run
   found an empty BTC 1m viewport when revisiting the series; the numerical
   runner had normalized it. A real LWC/React regression captures a historical
   view, clicks Return to realtime, changes products, then publishes late
   history. It reproduces the old history being restored after the round trip.
   Explicit follow-latest now retires that dataset/surface's remembered
   historical snapshot. Other datasets and surface configurations keep their
   own memories. A second real React case starts with a right-truncated window:
   the restore-window paint callback previously called the lower-level scroll
   and bypassed this intent reset. It now uses the same canonical latest action,
   retaining the existing dataset, store/version and interaction fences. Both
   direct and asynchronous restored-window round trips pass. The installed
   runner clicks the actual button once while right-truncated, asserts the
   sibling viewport is unchanged, rejects empty price viewports, and
   explicitly tests the return-to-latest product round trip. Numerical zoom is
   permitted only after verifying a nonempty, actually rendered price view.

15. **Bounded latest-window retry:** the actual one-click installed case at
   `8d5881340` issued a history read that returned 1500 ready/complete wire rows,
   but the chart retained its historical window. Its exact discarded-result
   branch was not recorded; a separate instrumented repeat succeeded and is
   diagnostic evidence only. A production cache/Feed regression establishes a
   concrete missing path: a concurrent newer storage revision correctly rejects
   the first HTTP snapshot as retryable, but the old navigation stopped after
   that one attempt. Explicit latest navigation now retains its owner for at
   most three bounded viewport reads, checking ownership, epoch, cancellation
   and unchanged coverage proof before publishing. It yields between retries,
   respects server cooldowns and stops on stale/inactive/terminal results.
   A bounded performance event records each decision for later attribution.
   This repair does not claim the original native discard was fully diagnosed.

16. **Closed-only runtime event input:** the `8defe72d4` soak failed its fifth
   cycle because one Python session permanently lacked a closed visible point.
   Raw WebSocket events show an empty Python patch for that exact timestamp,
   while the sibling received the correct point. A real Python runtime and
   production subscription regression reproduces this: the close event is final
   but the asynchronous latest query still contains its forming record plus a
   later bar, so the closed-only plugin legitimately emits no target point.
   Closed-only subscriptions now query a bounded window ending at the close
   event and fill/promote only that exact absent/forming row with the immutable
   event bar. An already final query row is retained, including amendments;
   wrong-time/forming event inputs are rejected. The descriptor's closed-only
   policy selects this path; Pine's own forming/stateful protocol is unchanged.
   The failing raw windows, empty wire patch, healthy source samples and
   pre/post real-runtime regressions are retained. The interrupted soak is not
   counted as a completed endurance result.

17. **Canonical reconciliation identity:** during the post-soak source check,
   installed diagnostics recorded reconciliation exceptions. Logging-only copies
   identified Binance ETH 6h/1M background batches mixing archive rows with an
   absent identity and REST rows with the explicit default identity. These are
   the same canonical series, but a raw optional-field comparison rejected them.
   Reconciliation now compares canonical identities, without mutating fetched
   evidence or changing source ranking. Truly different identities are rejected
   before timestamp deduplication, including fully overlapping batches. Six new
   regressions fail before repair; 62 identity/fence/reconciler cases and 380
   expanded backfill/storage/API/stream cases pass afterward. The coincident OKX
   timeout remains separately recorded; the Binance exception is not asserted
   to explain every OKX transport failure.

The first native attempt failed cold tail health; the second passed all 10 cold
and 10 hot trials, then failed the secondary-chart hosted-output gate described
above. Their receipts, traffic and screenshots remain alongside final evidence.
They are not relabelled as successful full runs. A later intermediate runner
also rejected a 1500-bar active hydration after only proving 500 bars healthy.
Its traffic shows a larger legitimate demand, so the qualified hot-switch setup
now proves the full 1500-bar target before measurement; that failed setup receipt
is retained as well. The native-range-confirmed attempt passed six cold trials, then correctly
rejected a 5m cache with no received realtime K-line events: subscribed/ACK and
visible cached bars did not establish health. That 180-second runner deadline
failure is retained; later cold-tail observation permits up to 300 seconds for
normal transport retries without changing any production timeout or health
criterion. The initial owner-browser
cleanup error is also retained separately from the configured failing regression.

A distinct intermediate `757ffb253` hot trial recorded one `active_hydration`
read despite the target being healthy at the pre-switch observation. The trace
was insufficient to distinguish an intervening invalidation from duplicate work;
its cause remains unclassified. Later ten-trial zero-read observations are
bounded repetitions and do not erase that earlier anomaly. The final driver
records both pre/post health and source notices for attribution.

An intermediate candidate's runner completed all ten cold renderer-pool trials
but assumed `cell-1` was the first saved chart after an earlier close/copy cycle.
That hot-setup error is retained. The repaired runner derives primary/sibling
IDs from actual workspace order and explicitly cites the identical-revision,
installation and profile cold receipt; no hot trial or soak is inherited from
that setup failure.

The first `8defe72d4` runner completed ten cold and nine hot trials, then
stopped before the tenth hot action because its target precondition had changed
from reuse to load. This is retained as a setup failure, not a measured healthy
switch. The driver now records a bounded wait for a healthy 1500-row target
before starting each hot timer and traffic delta. It neither changes cache
proof nor forces admission. The final runner cites only the completed ten cold
trials from the identical revision, application path and profile; all ten hot
trials and every later phase are rerun. Any precondition wait stays separately
visible in the receipt.

## Source and controlled-browser validation

- Full `npm run check` at `8d5881340`: 5082 functional tests, one isolated
  performance gate and 134 desktop tests, zero failures/skips;
  architecture/plugin/i18n/type/lint/build.
- After the final latest-window retry repair: all 5087 functional tests, one
  isolated performance gate and 134 desktop tests pass, together with fresh
  architecture/plugin/i18n/type/build checks and ESLint on all three changed
  files. The unchanged files retain the immediately preceding whole-repo lint.
  The log retains one existing `latestWindowScrollGateRef` cleanup lint warning
  and the existing Vite chunk-size advisories; neither is a failed check.
- Final changed source additionally received fresh TypeScript and affected-file
  ESLint checks after the cold-owner fixture was added. The intermediate fixture
  optional-field type error was corrected before this final check.
- Affected owner/feed/performance regressions: 64 passed.
- Backend public transport, sharing, lifecycle and Pyne removal: 115 passed.
- Production-minified Chromium market health: 13 scenarios, including the new
  cold retry regression; zero remaining workers or renderer exceptions.
- Revealed/offline replay: 11 controlled browser scenarios.
- Actual Pine HTTP/WS/SDK/core with controlled market transport: history prepend
  rebuilds the calculation origin and the next forming update; fixture shutdown
  confirms no remaining watches, callbacks, leases or registry entries.
- The earlier four-runtime source/adapter suites remain separately identified in the linked adapter delivery. Their changed
  frontend fingerprints were checked before the new acceptance repairs. The later
  indicator-flow fixture has 18 real-browser scenarios after the private/range
  publication repairs; worker/bootstrap and editor fixtures retain separate
  receipts. The latest restore-window change additionally re-runs all 11 replay
  scenarios and both real-chart latest-return paths.

Source/component, controlled browser and installed-app evidence are separate.
The replay fixture uses development React lifecycle with a minified fixture;
it is not presented as a production installed replay qualification.

## Installed-app protocol

`native-acceptance.mjs` installs no data into the user's normal profile. The
candidate is copied from its verified DMG into an independent installation
folder; its ad-hoc signature, bundled interpreter/dependencies, all 938 backend
Python files, all 174 frontend output files and two supported runtime packages
are verified against the source/build manifests. Packaging reuses the already
source-built verified Python/plugin runtime because those inputs did not change;
Electron Builder packages/signs the final frontend and current backend anew.
This is local macOS arm64 qualification, not notarized public distribution or
Gatekeeper download qualification.

Default-timeout whole-app restarts encountered repeated 30-second Binance
spot catalog failures on this network, including a later attempt with 495
provisional rows and no market-ready proof. Independent bundled-runtime DNS
variants could also succeed, so no resolver-specific repair is asserted. The
configured run explicitly sets the supported `INGESTION_HTTP_TIMEOUT=120` only
in its isolated app process. Its cold/hot measurements are redone under that
configuration; it is not default-network startup qualification. Data quality,
continuity/freshness gates and installed code remain unchanged.

The driver uses real bundled backend/plugins and public Binance/OKX data, with
no exchange-response substitution. It measures 10 cold frontend pools rebuilt by actual renderer reload on
one isolated persistent profile, with the same running backend/catalog/history, 10 healthy compatible hot switches, dual-chart
10000-bar navigation/trim isolation, four-runtime numerical values across the
finite BTC/ETH × 1m/5m matrix, an actual native minimize and 75-second renderer
network disconnect, a real >=30-minute dual-chart run with 10 switch/close/copy
cycles, full process exit and same-profile restart, then independent OKX source
values and current tail health. Visible-range numerical checks read actual Lightweight Charts `data()` for
candles and indicator series, require at least 20 comparable points per runtime and preserve window-relative JS versus hosted
calculation-origin semantics. An unsupported Pyne fixture must be rejected.

The timeline observer stores bounded samples. Native process-tree RSS/CPU,
renderer heap, shared cache, request/stream, scheduler and result/input owner
counters are sampled; hard cache and input subscription limits are asserted.
RSS includes shared pages, CPU is the operating system's process statistic,
heap is the main renderer only, and the final visible check matches actual LWC candle data/OHLC to the reported viewport; it is not GPU scanout. Timings
are observed network/workstation results, not a claim of CPU isolation or a new
P95 budget. Historic #123 fixed-input P0/P3 comparisons and rollback evidence
remain at their original revisions; this run does not rename them as current.

## Remaining qualification boundaries

Windows tooling returned a connector availability/429 error and the separate
remote-device inventory reported the Windows device offline. No Windows result
is inferred from macOS. Multi-hour endurance, OS sleep, arbitrary providers and
scripts, 16–64 charts, GPU scanout, complete heap/GC attribution, notarization,
and a historical backend-release downgrade are not covered by this bounded run.
The historical #123 extension matrix remains explicit; #154 worker/state/SDK
redesign and dedicated language/persistence work retain their own scope.

Public endpoint references: [Binance stream documentation](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md),
[OKX current port migration notice](https://www.okx.com/docs-v5/log_en/).
The production OKX adapter already uses 443; an obsolete-8443 standalone probe
is not treated as a production regression or a successful health receipt.

# Issue #123 P3: admission, display and asynchronous inputs

P3 is based on PR #136 (`f0b4d58b`). Shared HTTP/WS transports, their request
leases and per-window write ownership remain in place. This document describes
the implemented contract; measured acceptance evidence is recorded separately.

## Ownership and scheduling

`useKlineStreamRuntime` synchronously submits every validated event through the
existing owned transaction. It cannot import the display scheduler. There is
no second writer, hidden-write queue, or authoritative-commit bypass API in the
display scheduler. Final/amendment/reset semantics remain admission policies.

`createChartDisplaySubscription` subscribes to accepted commits. Main price
projection and its React legend share one display notification/version. Repeated
same-tail changes occupy one slot and retain incremental `series.update`.
When more than one structural change is skipped, the slot requests a projection
rebuild over the accepted reader, including deletions and viewport compensation.
It never applies only the last structural delta to an older display.

Hidden/minimized slots retain dirty state without scheduling RAF. Visibility
restoration schedules them even with no new market event. Final unsubscribe or
cell teardown cancels the slot; scheduler generation identity prevents an older
flush from deleting a replacement. Initial mounting and explicit chart type
changes still construct their projection directly.

The default frame runs at most two jobs, stops starting jobs after an 8 ms work
budget, and inserts no empty frame. A single callback cannot be preempted. Candle
display precedes preview work; an aged secondary slot gets precedence over fresh
focused work. `pendingFrames` includes retained hidden slots; `runnableFrames`
counts eligible work. `authoritativeCommits` counts valid final WS submissions at
the owned writer, including accepted no-ops; `displayCommits` counts display jobs.

## Stable asynchronous input

`captureStableSeries` returns a frozen range/limit snapshot, version, commit state
and `isCurrent` predicate. Live captures share already immutable rows and copy
only the selected array. The predicate also checks the captured session selection,
entry identity and owner liveness, so a retained reader cannot authorize an old
result after selection ABA, eviction or close. Mutable replay/static readers use
deep copies and exact version checks; their writers must maintain the version
contract.

Policies are explicit:

- `exact`: any data-version change invalidates the result.
- `forming-preview`: only updates of the same open tail may pass. A close, new
  candle, changed captured history, axis change or owner change invalidates it.
  This lets bounded previews finish under continuous input; it does not claim
  that the preview includes the latest forming price.
- `range`: every captured row must still exist unchanged and contiguously in the
  reader. Unrelated forming changes do not invalidate a closed-range result.

Local indicator sampling captures at most 2000 rows. It is used for both frontend
JavaScript and explicitly local indicators. Results, shared-cache writes,
deferred React updates and errors check the input fence in addition to lifecycle
and parameter identity. Hosted range requests retain server revision fencing and
also capture the locally held closed prefix. Empty or unavailable local history
does not prove the server's historical input; remote provenance still depends on
the server contract. Range apply may reject with `false`; settlement remains
retryable. An asynchronous apply receives `isCurrent` and must check it just
before publication; the scheduler also rechecks before recording success.

Synchronous readers still use live `snapshot()`/delta access. Export/freeze paths
must capture before their first await. These APIs do not turn a live array into a
stable asynchronous input merely by retaining its reference.

## Regression and rollback boundary

Tests cover immediate independent owner admission, dual-frame scheduling,
hidden/minimized recovery without a new tick, structural deletion after skipped
deltas, teardown, bounded/fair frame work, immutable capture, exact versus preview
policies, owner ABA/close, delayed correction and asynchronous apply supersession.
Architecture checks reject display scheduling imports at the WS/writer boundary.

Rollback is a source/build rollback to #136. Do not enable both implementations
or introduce a dual-writer feature flag. The same isolated QA profile can be
reopened on the parent and then on P3; no persisted market-data schema changed.
Keep P0/P1/P2 evidence and the retired-Pyne rejection checks intact.

## Acceptance status

The scoped results below separate observed correctness/performance from the
known remaining viewport defect and broader acceptance gaps.

### Measured candidate (2026-10-29)

Implementation `7d16f873bb08691a7f75eaad2ea5c5b3d112a797`, parent
`f0b4d58bdfec29bb7e94ebe39529ebf12b9ae0a5`. Later acceptance and browser-fixture location changes do
not change the measured renderer. Local evidence root:
`output/issue-123-p3-20261029` in the primary checkout. The PR/issue link the
portable evidence archive and exact-head CI separately.

The local full `npm run check` passed before the last browser fixture edit: architecture/plugin/i18n checks, typecheck,
lint, 4482 frontend tests, one separate performance test, 123 desktop tests and
production build. Final implementation typecheck/build were also rerun. The two
scheduler regressions fail against the parent. Twelve real Chrome Worker/React
checks pass, including stable-identity live input, continuous-feed progress,
hidden indicator restoration and delayed owner-ABA result/cache rejection even
without a React context change. These are controlled browser integration checks,
not an installed-app plugin acceptance claim.

Native tests use the production renderer, Electron 43.3.0 desktop host, isolated
profile and fixed synthetic BTCUSDT 1m input. Baseline artifacts were checked
against the parent build's SHA-256 inventory. For the minimized/restart tests a
copy of the same Electron host received a distinct QA bundle identifier to avoid
ambiguity with another Electron process on this machine. No normal profile,
exchange credentials, account actions or Windows process were used.

| Path | Parent admission P95 | P3 admission P95 | Parent series update P95 | P3 series update P95 | Parent update + 2 RAF P95 | P3 update + 2 RAF P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Single focused | 16.6 ms | 0.3 ms | 16.1 ms | 16.0 ms | 49.2 ms | 49.5 ms |
| Dual focused | 14.2 ms | 0.3 ms | 13.7 ms | 14.1 ms | 46.4 ms | 47.3 ms |
| Dual secondary | 47.3 ms | 0.2 ms | 46.9 ms | 14.7 ms | 80.6 ms | 47.7 ms |

Each layout/build has one warmup and five measured runs of 200 forming updates,
requested at 50 ms intervals, over 1500 final rows plus one forming row. Every
visible chart has 1000 admissions, incremental series updates and two-RAF
samples. All 20 measured runs preserve final OHLCV/finality; observed full
`setData`, additional Kline HTTP and >50 ms long tasks are zero, physical WS is
one. Existing focused comparison budgets (single 21/62 ms, dual 20/61 ms) were
not raised; secondary also fits the dual display comparison. This is descriptive
fixed-input evidence, not statistical significance, GPU completion or cold/live
network latency. This task ran no build/test/benchmark alongside measured runs;
the shared workstation was not CPU-isolated.

The performance verifier combines unchanged history/count from periodic full
snapshots with the final direct source and series notifications. A periodic
snapshot can precede the last input. It filters actual changed tail deltas, so
later metadata no-ops carrying the last input label are not counted as ticks.
The functional observer adds full displayed rows and viewports only after the
performance runs; both observer sources are retained.

Native functional results:

- Two same-series charts retain distinct window IDs and one shared physical WS.
  Left-only zoom changes no right viewport. Hidden left chart admits seven new
  rows and a valid historical amendment while its displayed rows remain frozen;
  restore with no new tick displays all 1511 rows and retains the left range.
- Actual native lifecycle confirms minimized/visible=false. Three new bars plus
  200 updates at requested 5 ms spacing are admitted by both owners while both
  series remain unchanged. Exactly two dirty slots remain, zero runnable slots.
- During that minimized interval WS and HTTP are blocked; four more bars and a
  historical amendment are made offline. After network/visibility restoration
  without a new WS candle, both 1507-row sources match every authoritative
  OHLCV/finality field and both displayed series match their source OHLC. The UI
  remains waiting for real-time data instead of claiming live solely from ACK.
- Same isolated profile is closed and reopened on P2, then P3. Dual selection,
  independent owners, one physical transport and exact held rows/display survive.
  Parent and P3 renderers are never enabled together. This is renderer rollback;
  the desktop host code changed only in its opt-in evidence harness.

### Initial viewport finding, follow-up fix and remaining coverage

A separate native probe confirmed an existing viewport defect: after a seven-bar
burst, an old-bar amendment moves the maximized visible chart left by 18 logical
bars. It reproduces on both P2 and P3 (`viewport-probe-*-before/after.json` and
`viewport-known-issue.json`). Initial offsets differ, but both move by 18; no
claim of identical initial viewport is made. In P3 the hidden chart does not
move; P2's hidden chart also moves. Data/display equality is unaffected. This was the initial P3 result. The follow-up below fixes this path; the complete
viewport acceptance matrix still depends on the separately declared coverage.

The follow-up changes bounded equal-time suffix corrections to LWC historical
updates. Popping/re-appending rows temporarily changes the axis even when the
final timestamps match; it is therefore unsuitable for an amendment. Structural
changes retain the full-rebuild/anchor path, ordinary forming/appends retain their
existing fast path, and a failed historical update rebuilds the complete data and
compensates the captured viewport. Regression tests cover the unchanged time axis,
burst/correction data integrity and partial-update fallback.

A fresh native baseline/candidate comparison uses the same 500-row starting
window, seven appended rows and a correction at source index 10990. The maximized
visible range starts at [407.75, 504] in both builds. The baseline ends at
[389.75, 486]; the candidate retains [407.75, 504]. Both sources hold 507 rows and
share one physical WS. Follow-up evidence is recorded under
`output/issue-123-p3-followup-20261029` and linked from the issue/PR. The initial P3
archive remains historical evidence rather than being overwritten.

Repeated native drag/horizontal-scroll attempts did not produce a confirmed pan
in this run. Independent zoom, live return, hidden restoration and owner isolation
are observed; the full 10000-row A-history/B-live navigation scenario from P1 was
not freshly revalidated on this candidate. Do not label those attempts passed.

Also unverified: full installed/notarized app interaction; native indicator/plugin
creation and every hosted provider; export/replay workflows beyond the tested
snapshot contract; OS sleep; long outages and soak; 16–64 charts/heavy callbacks;
full-application retained heap, allocations and GC; real network variability;
GPU presentation; Windows. The synchronous writer now accepts every valid input,
so a short high-rate burst does not establish sustained-rate CPU/memory limits.
A frame budget cannot preempt a slow callback. Local captures cannot prove a
remote server's historical input, which still requires its revision contract.
Issue #123 remains open; the full matrix is not accepted by this scoped delivery.

CI initially caught the browser-only writer fixture outside the existing test
namespace. It was moved under `src/test/__tests__` and the browser harness import
updated, preserving the production writer rule. Final architecture/type checks
and the real browser suite were rerun; CI validates the resulting exact head.

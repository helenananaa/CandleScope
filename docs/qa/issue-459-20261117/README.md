# Issue #459: actual batch coverage and bounded dispatch turns

B's implementation and scoped validation build on #458/#460/#461 (PRs
#466/#464/#465). This item closes independently under the split-task rule.
Overall cold net readiness <=3 seconds, actual total time and the final native
matrix remain #463. #447 stays open; review, CI, merge and release are separate.

Product backend: `9258f0d2f9fe6aaf799b728ef0ce98eab9f62ada`, based on
`1b0673adbbf2885f4c3b29a770f0353940a5ac94`.

## Reproductions and changes

Five original scheduler cases fail on the base and pass after repair:

- A running parent's envelope covers a new hole that its actual planned ranges
  never fetch; the new demand was incorrectly deduped into that parent.
- The same hole can disappear during covered-demand dedupe of a pending parent.
- A plain running parent can absorb a required mixed-source consumer, or an
  optional bounded-batch consumer, without executing that consumer's contract.
- Overlapping planned windows generate duplicate target business chunks.

Cover checks now use the normalized actual planned range union. Pending merges
retain a newly requested hole; active work that cannot cover it leaves a real
successor. Overlapping/adjacent target opens are normalized before splitting,
without filling discrete holes. Off-grid bounds retain ordinary inclusive
adjacency, and calendar adjacency uses the existing interval spec.

Required mixed execution, optional bounded fine-source batching and ordinary
requests keep distinct coalescing contracts. Existing identity, hydration,
trusted-finality upgrade and acquisition/deletion checks remain intact. The
coordinator remains the qualification owner; the scheduler does not force all
intervals into mixed composition or introduce another planner/downloader.

A further four-chart/local-burst case fails before the fairness correction.
The previous aged dispatch selected the oldest queued chunk and erased all
other waiters' bypass debt. Two old owners could repeatedly win aged turns
while newer charts waited. Aged work now uses the existing per-owner turn and
retains other owners' debt until they receive their own dispatch. The existing
2-second local burst, eight-bypass aging policy, same-series exclusion,
background cap, quota/probe ownership and interactive reserve stay in force.
No concurrency, source budget or retry limit was raised.

## Bounded observability

The existing scheduler exposes at most **256** completed-attempt diagnostic
receipts, with sequence IDs and explicit dropped count. These are not coverage,
quota, persistence or cancellation authority. Every receipt contains bounded
scalar IDs/ranges, nominal work-plan fields, acquisition revision, dispatch
attempt, enqueue/start/finish times, ready-queue and ineligible wait, worker
occupancy, reported engine/reconciler times, defer reason/bucket, running/ready
counts, owner and up to 32 consumer IDs. Current parent snapshots include
bounded per-consumer completed/remaining chunk counts, scope/generation and
explicit truncation. They do not resolve a parent future from partial work.

`ready_queue_ms` includes waiting behind the same-series owner, dispatch slots
and internal scheduling; it is local time. `not_eligible_wait_ms` includes
probe, retry and public quota deferrals. It is **not certified exchange waiting**
and cannot be deducted from readiness. `worker_elapsed_ms` includes the callback
and completion/finalization; engine/reconciler reported phases can overlap it.
Do not sum/subtract these as exclusive stages. Retained source-route/HTTP and
storage-health records supply existing fetch/archive-parse/import/aggregate/
write metrics separately; exact per-chart critical-path attribution remains F.

`interval_work_plan` is the existing conservative single-base equivalent. For
required 10007m mixed jobs its nominal 1m row equivalent is not the physical
mixed input count. The engine still enforces its mixed-source/refinement budget,
finer-source precedence and exact source routes. Padding is in target buckets.
No nominal count is relabelled as a measured provider download.

## Scoped checks

The broad integration selection passes **866/866**, no failures/skips, in
154.29s. It includes 69 new cases plus coordinator/planner, query/materialization,
streaming, native/mixed history, CCXT transport, source/cache/publication,
cancellation/re-subscription, routing and #461 fence regressions. One additional
cheaper-coarse-source case passes after that run: a qualified 203-target 45m
page keeps its cheaper 15m route and single larger ordinary batch (618 planned
rows), rather than being forced to 16-target mixed work. The current
`run-tests.sh` includes that supplementary case too. No backend code changed
after the broad run or the native product.

The 60 arithmetic cases span 89m/97m/101m/10007m, 1/7/16/128/203 target pages,
and ordinary/optional/required contracts. Every actual open appears once;
each chunk's target count, source factor, padding, source-equivalent budget and
original ledger range agree. Existing larger/cheaper native/coarse pages remain
available. The large-prime contract proposes at most 16 targets when required;
existing finer history may require the existing smaller engine refinements.

The other new cases cover active/pending plan holes, contract preservation,
shared-consumer disconnect, per-consumer progress, four charts plus maintenance
under local bursts, configured concurrency, bounded immutable receipt snapshots
and public-admission deferral timing. Existing coordinator tests cover stale
scope generations, late thread submissions, one-consumer revocation, retained
shared demand, failed retry, source probes and physical-worker cancellation.
Ledger completion and canonical adoption remain after durable verification.

The first five-failure report and the separately reproduced fairness failure
are retained. An intermediate 68-case run passed 67 and failed fairness before
that correction. The 193-case scheduler/coordinator/planner follow-up passes.
These failures are not described as unrelated or pre-existing.

## Public-input source replay and same-input work counts

`public-minute-fixture.json.gz` contains 9,184 actual closed public Binance
USD-M BTCUSDT canonical minute rows, extracted read-only from #458's stopped
native profile. Its source product/database hash and ranges are embedded.
It is a self-contained public-data replay fixture, not a new exchange session.

`replay-batches.py` runs the existing scheduler -> BackfillEngine -> canonical
SQLite writer/reducer, with recorded rows supplied by a controlled fetcher.
It preserves the coordinator's actual read-repair requester metadata. Each of
89m/97m/101m runs once with empty market storage and once with full minute inputs
already local. All six scenarios produce 32 correct targets: **192 closed
outputs**, independently checked against raw inputs for all nine OHLCV/enhanced
fields using first/last, min/max and `math.fsum`; zero mismatches. Local-source
runs make no controlled fetch calls. Every emitted source task is also checked
against its actual child range, rather than the parent ledger envelope (C).
The actual engine's durable revision/finality checks remain active (D).

Same fixture and script on base #466 vs this candidate:

| Per 32-target scenario | Base | Candidate |
| --- | ---: | ---: |
| Executed business chunks | 3 | 2 |
| Repeated requested target opens | 8 | 0 |
| Controlled source fetch calls, empty storage | 4 | 4 |
| Controlled source fetch calls, minute inputs local | 0 | 0 |
| Decoded controlled inputs, 89m / 97m / 101m cold replay | 2,848 / 3,104 / 3,232 | 2,848 / 3,104 / 3,232 |

Both versions remain numerically correct in this overlap replay because the
existing canonical engine already avoids re-fetching covered inputs. The new
change removes redundant business chunks/planning; it does **not** demonstrate
fewer physical network requests or bytes. Controlled fetch calls are not wire
requests. Normal ranges and required mixed actual source routes are also
covered by the separate native/transport/routing tests.

All raw total and phase times are retained. Initial candidate replay times
(452–1,151ms) exceed the separately measured base times (216–507ms), but the
candidate run overlapped the broad test selection and the base run followed it.
They are same-input work-count comparisons without matched host load; no
latency improvement or regression is established from that timing pair.
The native diagnostic began after the broad suite and those replays; the
supplementary single coarse-path test ran during that diagnostic. None of
these timings is a joint performance qualification.

## Native boundary

The inherited four-chart driver runs with issue 459 and a new empty profile,
real public Binance USD-M, 89m/97m/101m/10007m plus EMA20/60 and frontend-JS close.
It uses a strictly signed retained macOS arm64 frontend/runtime/plugins and a
complete committed backend overlay, not a fresh release. The existing local
QA proxy is selected only for that process. No seed or substituted response
is used in this native run. Windows qualification is separate.

The observation records actual wall time, source routes, public HTTP, queue
receipts and owned process resources; raw net time stays unknown because exact
external critical-path blocking is not certified. Current/partial data,
remaining queue time, source/probe failures and revision rejections are retained.
Full four-chart readiness, 128/127 bars, indicator consumption, ten-minute live
updates, hide/restore, switches and saved restart remain #463. Runtime prefix
recovery already tracked in #462/#452 is not declared solved by this item.

## Retained native result

Apple M1 MacBook Air / 16 GiB / macOS 26.6.2. The stopped run retains **64**
attempt receipts, sequences **1–64 with no sampled gaps**: 42 completed,
2 partial, 19 public-admission deferred and 1 retry deferred. These are attempt
statuses, not 42 fully verified chart loads or parent ledger resolutions.
All four primary intervals have completed chunks (7/7/9/4 respectively), and
an ETHUSDT spot daily-open maintenance job also completes. Forty-seven aged
dispatches and 17 uses of the existing foreground reserve are observed.
The nominal concurrency is 1, observed peak 2 through that existing reserve;
no setting was raised. The largest observed ready queue contains 68 chunks.

| Primary interval | Attempt receipts | Maximum local ready-queue wait (ms) | Maximum ineligible wait (ms) |
| --- | ---: | ---: | ---: |
| 89m | 11 | 179,277.686 | 28,735.268 |
| 97m | 13 | 182,340.269 | 28,677.423 |
| 101m | 16 | 173,757.721 | 28,616.818 |
| 10007m | 5 | 154,926.671 | 12,823.101 |

These long waits remain visible. Bounded dispatch turns do not imply a
3-second queue-latency guarantee. Same-series dependencies and global worker
occupancy remain local waiting; they are not relabelled as exchange limits.
The recorded bypass counter saturates at eight; eligibility/same-series/quota
constraints still apply, so it is not a measured absolute count of every
intervening grant. Reported per-attempt phase values and queue snapshots are in
`scheduler-receipts.json.gz` and `scheduler-states.json.gz`.

Demand starts at `1794840631349` and observation ends at `1794840837904`:
**206,555ms actual wall time**, censored before full readiness. Displayed counts
are **62 / 60 / 52 / 65**, with loading pending. Startup was a separate phase;
its exact duration was not instrumented. Net time remains unknown/unqualified;
no cumulative requests, ineligible waits or overlapping worker timers are
subtracted. This item does not assert the overall 3-second goal has passed.

The stopped-database independent SQL/math oracle compares **61 + 56 + 51 =
168** persisted closed 89m/97m/101m targets against complete trusted-final minute
inputs, including all nine fields and time boundaries: **zero mismatches**.
Missing/incomplete/current inputs are explicitly skipped. No native 10007m
numerical, indicator-consumption or lifecycle qualification is claimed.
All 1,010 backend file hashes, the unchanged ASAR and strict signature verify
after execution. The owned process tree exits in **6,970ms**.

Three actual mixed-target changes and one native-input-window change are still
rejected. A realtime history-target generation-expired traceback also remains
in the raw log; no recovery/root-cause conclusion or sustained-update pass is
inferred from this run. #462/#452 and the final #463 matrix remain open.
Original failed/development reports, same-input base/candidate receipts, actual
wall times, public input fixture and raw native records are indexed by SHA-256.
Full profiles, databases, apps, plugin runtimes and control credentials stay
local. The self-contained public fixture is sufficient to repeat the source
comparison without those private profile files.

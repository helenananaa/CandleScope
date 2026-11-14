# Explicit bounded composed history admission

Base main: `ec3eb0ece1b978dfe3071e7c8635ea51e1723521`.
Cold planner runtime: `e08bd3233`; explicit read mode: `d78c7d46a`;
dispatch availability correction: `9cfd903a7`.

Previously, the 10007m frontend admission could only issue a target-storage
probe because the minute-expanded estimate exceeded its source-row budget.
Qualified default USD-M fixed-UTC history can now request a finite page through
the existing H127 executor. The ordinary policy remains unchanged for smaller
requests and unsupported providers/identities/calendars remain target-only.

The frontend validates the real provider capability, native grids, calendar,
identity, finality, nine-field mask and qualification evidence. Its conservative
bound admits 406 history targets and stages the first 128. This is permission
to request bounded execution, not a claim that historical data exists or that
all 406 targets form one admitted backend plan. The original source-aware
scheduler splits that demand into bounded jobs. Indicator dependencies and
readiness gates remain intact.

An explicit composition contract follows initial load, retry, hydration, left
pagination and range readback through the existing feed/broker and DataManager.
Separate history/before/range URLs fail on older servers instead of silently
losing the constraint. Existing complete stored targets can be reused. Contract
or configuration changes reject unavailable execution; read/work-budget deferral
retains only trusted stored partial data, with pending/incomplete state and no
new source-expanding fallback or verification repair. Backend jobs validate the
same contract again before selecting the original mixed executor.

Native cold observations exposed a separate business/physical scheduling gap:
a deferred other-series chunk could protect quota while every business slot it
could use was occupied. The active job could then be blocked by the queued
job's priority. Quota protection now consults the original scheduler's actual
capacity, foreground reserve, shared-input conflict and background lane, as
well as the existing series lane. No queue, quota ledger, cache or writer is
added. A controlled original-owner regression fails on the old source and passes
with one or two slots; the old same-series case remains covered.

Validation before the dispatch correction: complete backend 2,423 passed / 66
warnings / 587.77s; complete frontend check passed (5,105 main tests, 1 isolated
performance test, 134 desktop tests, architecture/plugins/i18n/typecheck/lint and
production build). Lint retains one pre-existing SingleChartPanes warning; Vite
retains its bundle-size warning. The 13 new default DataManager/real SQLite/API
contracts include actual eight-target completion through the original
coordinator/ledger. After the dispatch correction, 155 coordinator/admission/
priority tests passed. The first narrow selection hit the existing same-series
three-second startup deadline; its receipt is preserved, with no timeout or
assertion adjustment. The subsequent complete relevant files passed.

The first ordinary native run and two diagnostic-only runs of `d78c7d46a` all
failed the original 128-bar/marketReady gate. Their failures, task traces,
resource samples and complete process exits remain preserved. Four-chart cold
qualification, the later indicator/soak/hide/switch/recreation/restart sequence,
paired total resource/latency evidence and other provider qualification remain
pending at this document revision. Source qualification and planned request
costs are described in `../mixed-history-admission-127-20261114`.

The retained macOS arm64 runtime/plugins/desktop dependencies are unchanged
from `ef8f0e0fa6df299a823f4460b701eb1c3c98361f`; the complete 1,006 tracked backend
files and fresh 174-file frontend dist were overlaid, hashed, ASAR-integrity
updated and strictly signed. This is an assembled native candidate, not a fresh
release build. Profiles, databases, bundles and credentials remain local.
`archive.py` publishes finite redacted receipts and original/published hashes.
No parent issue is considered complete on these component or partial results.

The subsequent ordinary four-chart run of `9cfd903a7` also failed the original
180-second first gate: 86 / 71 / 3 / 0 visible bars, none marketReady; four
K-line latest HTTP 500 responses were observed. Its full 11-process tree exited.
The complete backend integration was running concurrently, so this is an
explicitly loaded failure observation, not a paired/native performance result.
One later read-only repeat of a failed latest URL returned 200 before shutdown;
it does not explain or erase the original 500 responses. Error-body capture and
an independently loaded follow-up are required before product qualification.

Runtime `4e1078494` adds a conservative resident/inflight-input existence query
on the original B130 owner; canonical counts may prune an impossible local
cover only when this shared input path has no relevant retained work. Ordinary
and explicit mixed reads use the same optimization. Counts never certify
finality, field coverage, actual grid tiling or a write. The real SQLite/shared
reader regression preserves a resident coarse-summary cache hit.

The 23 HTTP500 responses in the `47ce5e5ea` four-chart run were captured as
`prerequisite stream futures:BTCUSDT@1m is error`. The new typed lifecycle failure
still rolls back the start's leases and intents. The two latest-read endpoints
can then read only bounded existing targets and report retryable pending;
repair=wait cannot turn the failed live prerequisite into another historical
repair. A requested revision floor remains enforced. Unexpected runtime errors
remain errors. The shared target-only method now permits an omitted time range
while still requiring a finite limit; no base read is introduced.

Current-source verification: 136 stream/read/GC checks passed, including default
SQLite, empty/stored targets, both latest routes, revision floor and unexpected
error behavior. Original source fails all four initial latest-start regressions.
The complete integration collected 2,448 tests: 2,447 passed, one older empty
work-budget fixture missed its injection point after the new negative preflight.
The fixture now supplies real cross-boundary daily rows and asserts entry into
the budget fault; the original no-repair assertions remain. Its complete demand/
composed files then passed 36 checks. This is a preserved failed full run, not a
claim that a later complete CI run has passed. Architecture checks passed.

Three alternating fresh-process pairs (`query-*-2/3/4`) use byte-matching copies
of the retained single-chart public database. Provider declaration bootstrap is
outside the query timer; no other local test runner was active. All six return
the same 19 targets and all nine raw fields/source/finality, equal their actual
materialized read, keep the source database bytes/revision unchanged and write
zero targets. Baseline CPU is 66.573/65.570/67.743ms; candidate is
55.811/57.848/57.432ms. This one small retained-data case does not establish
product latency percentiles or total CPU/RSS/GC improvement. Initial exploratory
trials 1 ran under a concurrent full integration and remain separately retained.

The single-chart `9cfd903a7` run with no other local test runner also missed its
180-second gate: internal bar count 20, marketReady false and EMA point counts
1/0. Its directly inspected screenshot still shows a loading overlay; this is
not visible-chart or indicator-warmup qualification. The final health snapshot
retains 70 recent kline attempts, all HTTP200, and local admission deferrals;
the UI's rate-limit count is not proof of upstream HTTP429. Nineteen background
chunks had completed. Four-chart `47ce5e5ea` ended at 222/148/118/6, only 89m
ready; it had a 33-second focused test run during part of the observation and
is not a strict isolated performance sample. All failures and exits remain.
A final ordinary native observation of `4e1078494` is tracked independently.

Final assembled-native observation: runtime `4e1078494`, frontend dist unchanged
from the checked build, no concurrent local test/benchmark runner. The original
first viewport gate failed at 22/51/196/3 internal bars; all four marketReady
flags remained false and no chart is qualified. No observed API response was
HTTP5xx. This does not itself prove that every controlled stream-deferral branch
was exercised live. The attempted later JavaScript indicator probe, ten-minute
soak, hide/restore, switch/recreation and restart sequence was not reached.
Full process exit, source/ASAR hashes and after-run strict signature are retained.
The original first-ready gate was not relaxed. #126/#127/#129 remain open;
#130 remains closed. Next work retains the cold batching, current large-bucket
initialization, partial visibility, full resource/correctness and original issue
acceptance obligations. A passing narrow read/dispatch fix is not joint closure.

The last ordinary-history verification guard is tested after the assembled
`4e1078494` native observation: all read-admission/contract/materialized tests
passed 115 checks. Both ordinary and explicitly composed history/range reads now
require a stable admitted read before verification can submit new repair work.
Real source gaps still use the original demand owner. These final guard lines
were not overlaid into that earlier native app and carry component/API evidence
only; final PR CI must run the delivered source. No passing full product/native
qualification is claimed for this batch.

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

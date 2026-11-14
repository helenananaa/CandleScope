# Preserve committed partial targets when mixed source coverage is unavailable

Related issue: #127. Base: `14049ae9b2f2980f5e5cc5e3f23dd99f9feeddd2`.

A real stopped USD-M cold-start profile contained 133 trusted closed 89m target
bars. For a 221-target page, the ordinary query returned zero bars although the
materialized reader returned those 133. The optional mixed reader could not
prove full source coverage; the legacy minute window exceeded the existing
10,000-row query limit, so its recovery branch returned an empty page and
requested the whole target range.

The existing target probe now travels through that recovery branch. The query
returns only its individually trusted, aligned closed targets, keeps the page
pending/retryable/incomplete, and schedules only uncovered positions inside
the bounded planned window through the original scheduler. Before/count reads
retain older sparse canonical targets without expanding that repair window;
explicit range reads remain inside their supplied bounds. Existing partial
targets are not rewritten and are not counted as complete materialized hits.
The original acquisition/revision/cache admission fences remain responsible
for concurrent changes; no new cache, writer, queue or source permission exists.

The added real-SQLite/default-DataManager contracts cover range and before
queries, sparse older history, exact repair span submission, independent-writer
target deletion/source deletion/amendment, untrusted target sources, and the
real zero-wait HTTP viewport route. Fine-source deletion leaves an independently
committed target representation intact, but a stale in-flight read is fenced
and a later read cannot recreate fine coverage or rewrite the old target.

Before the patch, the original range/before regressions both failed (zero
instead of 70 stored targets). Final runtime-focused verification passed 220
tests; the local full backend collection passed **2397 tests / 66 warnings in
667.65s**. That collection started before the last test-only exact-span
scheduling contract was added; the final default module including it passed
**42 tests / 1 warning in 19.09s**. Final CI must collect all current tests.
Architecture, F821/F823 and whitespace checks passed. See the archived receipts
for exact counts, source/diff provenance and command outputs rather than
treating this paragraph as a full-suite or native qualification claim.

Intermediate failing test receipts are retained too. The fixtures were corrected
to observe their initial SQLite writes through an explicit minimum revision,
to run a concurrent producer outside the reader's ContextVar acquisition scope,
and to respect fine-source deletion's existing independent-target semantics.
The final independent-writer and fresh-reader assertions enforce the actual
product contracts; these fixture corrections did not loosen runtime fences.

`probe.py` makes a SQLite backup from a retained stopped-profile database opened
read-only, uses the real DataManager without admitted network work, and compares
all raw aggregation fields and finality/source values with the materialized
reader. It verifies that the original database bytes remain unchanged. Run:

```
python docs/qa/partial-mixed-history-127-20261114/probe.py \
  --root /absolute/checkout \
  --database /absolute/stopped-profile/candlescope.db \
  --output /absolute/new-output-directory
```

The old failed native runs are separately retained in
`../aggregation-joint-acceptance-20261114`. This patch does not remove the 10007m
initial history budget guard, establish a passing cold viewport, provide a
full resource/indicator/strategy matrix, or complete the parent issue gates.

## Targeted native observation

The complete 1,005-file backend at `b43d5a5118635109f12f52a4d645d531d77c6526`
was overlaid in a separate retained-runtime macOS arm64 app. Frontend/dependency
paths were unchanged; all backend/asar hashes and strict deep signatures matched
before/after. A new profile received only a canonical SQLite backup of the
previous real-public-data USD-M run. This is a retained-history observation,
not a cold-load test.

The ordinary first 89m history response returned **133 bars, pending,
complete=false**. Real repair/realtime work continued normally; the inspected
screenshot and workspace later showed **213 bars** and local EMA20/60 output
of **194/154 points**. At that observation `loading=false`,
`initialHistoryPending=true` and `marketReady=false`. Thus partial history was
visible without being promoted to complete history. All 11 captured owned
processes exited. No custom-JS input comparison, strategy test, long soak,
restart or paired CPU/RSS qualification was performed in this targeted run.

The first harness attempt configured during `restoring-study`, received
`HISTORICAL_STUDY_ACTIVE`, then called a nonexistent control-client close
method. Its receipt, screenshot, driver, log and post-exit process scan are
retained under `partial-warm`; it has no complete captured process-tree receipt.
The corrected `partial-warm-v2` waits for the original live owner before
configuration and uses the established bounded app-quit/owned-exit check. Its
driver hash is checked. The first failed harness does not count as a product
regression or a successful native run.

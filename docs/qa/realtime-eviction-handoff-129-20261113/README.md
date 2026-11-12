# Eviction buffer publication ownership and retry transfer

Refs #126 / #129; parent issues remain open. Base `39fc06ef4205732f6d2a030b41233ebf9651e0e6`.
Product `4d62f15ed16c3ed9a5c6125caf9aa0992d4296a5`; exact source hashes and raw
receipts accompany this report. Main's subsequent #385 is documentation only.

## Reproduced defects and ownership

The previous drain iterated a live buffer across callback awaits, then cleared
that entire list. Concurrent or reentrant drains could publish the same head.
A source-backed callback failure left the raw item in the buffer even though the
publisher already owned a retry snapshot. After that snapshot was acknowledged,
a later drain sent the raw item again with a new delivery ID. Successful earlier
items also remained retained until the last callback finished.

Each drain now claims/removes one raw item synchronously before awaiting the
existing public closed/expired emitter. A small per-pipeline claims dictionary
registers those already-held references with the realtime-state owner through
success/error/cancel. It adds no payload copy or independent delivery queue.
Successful items release immediately, and empty claim dictionaries clear capacity.
Actual dictionaries, tokens and states participate in estimates/opt-in heap roots.

A task-context observer records the synchronous transfer to the publisher's
existing source retry snapshot before callbacks can suspend. On failure/cancel,
raw data is restored only if that transfer did not happen. This also handles a
concurrent retry acknowledging the snapshot before the original callback resumes
and fails: current dictionary membership alone cannot prove ownership history.
The same source delivery ID and existing durable owner remain responsible.

Ordinary pre-handoff failures and non-source cancellation preserve the raw item.
Silent drains discard only unclaimed items, and cannot clear a different task's
active claim. Callback reentry can drain later records without recursion on the
claimed head or a lock held across callbacks. Existing callback concurrency and
public emitter overrides remain; this is not the separate R129 preview/barrier
scheduler. No budget increase, canonical deletion, new writer or revision ledger.

## Verification

- Two unchanged probe cases fail against the **complete** base backend and pass
  against this product: concurrent same-head publication and source retry then
  raw re-emission. Baseline and product logs are retained.
- Ten new owning cases cover those defects, normal/source cancellation, target
  detach with a suspended claim still accounted, concurrent early acknowledgment,
  callback reentry, pre-handoff deepcopy failure/observer reset, silent drain,
  and actual BarStateEngine active/closed capacity eviction for closed/expired.
- Final source/publication/lifecycle focus: **35 passed**. Final expanded
  aggregation, source fork/revision/SQLite/durable recovery, history, caches,
  queries, retention, architecture and Pyne retirement regression: **1737 passed**,
  six existing warnings, 120.90 seconds. CI selects the new owning tests.
- Architecture and diff checks pass. No new network, native, endurance or whole
  resource-budget acceptance is claimed. Current changed-backend native attempts
  remain [failed/pending](../realtime-handoff-native-126-20261113/README.md).

Retained attempts: the initial 1727-test run passed before the final claim-table
metadata refinement/new cases. The next expanded run had 1735 passes and two test
expectation failures: new tests wrote `closed`/`expired` while the established enum
values are `bar.closed`/`bar.expired`. Only those expectations changed; production
values and publication semantics were preserved. Final focused and full reruns
pass. Logs/XML of both attempts remain indexed.

## Controlled cost and lifetime comparison

`measure.py COUNT` builds the same 97-component source-proof fixture in a fresh
process for each variant, detaches its target, queues COUNT controlled closed
handoffs and suspends the last callback. It measures the actual registered
MemoryBudget roots. Construction and heap traversal are outside explicit drain
CPU/wall timings; all 32 batches assert identical ordered bucket/nine-field traces,
matching result hashes, empty buffers/pending events and zero reservations.
Synthetic direct buffers do not establish source authority or network qualification.

| Handoffs | Baseline / product held states | Baseline / product visible retained bytes | Baseline / product drain CPU P50/P95/P99 us |
| --- | ---: | ---: | ---: |
| 1 | 4 / 4 | 253763 / 253995 | 405/426/452 vs 411/434/473 |
| 128 | 131 / 4 | 3426858 / 254023 | 50819/51598/51666 vs 50848.5/51288/51427 |

These final sequential fresh-process measurements ran **after** our regression
processes ended, product first then baseline. Earlier pilot pairs overlapped our
regression work and had much higher CPU costs; they are retained and not used as
performance qualification. Other host load is uncontrolled. This is one
instrumented-host comparison, not a stable latency/throughput or RSS pass.

After drain completion, registered heap is baseline 368 / product 432 bytes;
the extra empty claims dictionary is 64 bytes per retained pipeline. The new
registry references existing coroutine arguments, and payload snapshots retain
the existing copy behavior. Whole-process peak RSS/GC and all estimates/counters
are retained but are not attributed as aggregation savings. Fixed component
weights can still underestimate large source-proof graphs; #126 byte calibration,
admission bounds and #129 retention/reconstruction remain open.

```sh
CANDLE_DATA_DIR="$PWD/output/eviction-tests" PYTHONPATH=backend python docs/qa/realtime-eviction-handoff-129-20261113/run-regression.py
PYTHONPATH=/scratch/full-baseline/backend python -m pytest docs/qa/realtime-eviction-handoff-129-20261113/ownership_probe.py -q
PYTHONPATH=backend python -m pytest docs/qa/realtime-eviction-handoff-129-20261113/ownership_probe.py -q
PYTHONPATH=backend python docs/qa/realtime-eviction-handoff-129-20261113/measure.py 128
```

The original #126/#129 completion definitions still require their remaining
writer/read inventory, byte bounds, long-run workload, on-demand preview and
semantic barriers, state reconstruction and applicable consumer/native matrices.
No parent issue is marked accepted by this repair alone.

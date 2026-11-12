# Realtime publication and eviction payload accounting

Refs #126 / #129; parent issues remain open. Base `55edd33856476f7c3a191d05ed9b951207b31d11`.
Product head `b3564b16f4ac63dd26dd7c2942c26a1dcc17a806`; source hashes and full raw receipts accompany this report.

## Reproduced gap and change

The old realtime-state owner omitted pending source retry snapshots, suspended
publisher dispatch/callback copies and convenience-call builder arguments, and
engine closed/expired eviction buffers. Removing the last target could therefore
report an empty owner even while those payloads were still reachable. Seven
initial accounting contracts failed against the baseline; their log is retained.

The existing owner now counts those containers and registers their actual roots.
State identity deduplication avoids charging one aliased current/previous or
resident/handoff state twice. Immutable component references may still appear in
multiple state indexes; opt-in heap traversal deduplicates the actual graph.
The publisher registry only references payloads its coroutine frames already
hold: it creates no extra BarState/event snapshot. Registrations release in
finally on success, error and cancellation; empty dictionaries clear burst
capacity. Diagnostics expose counts, never private payloads.

Retry previously captured a list of every pending event, retaining acknowledged
payloads until the entire retry batch finished. It now captures delivery IDs,
looks up one pending event at a time, and releases the acknowledged item before
advancing. The unchanged `retry_probe.py` fails against the full baseline and
passes against this product. ID tuples and concurrent retry inputs are accounted
for too. Existing delivery IDs, pending owner and callback failure semantics are
preserved; there is no new queue, durable writer or revision ledger.

No global/owner budget is raised and no active, correction, pending or canonical
data is removed to satisfy a budget. Exhaustion retains the existing retryable
admission behavior. This fixes visibility and one retry payload lifetime; it is
not bounded retention or whole-runtime memory acceptance.

## Validation and preserved attempts

Final regression: **1,727 passed**, six existing warnings, 216.53 seconds.
Final focused source/publication run: **24 passed**. The 15 new owning tests cover
pending retries after detach, budget admission, current/previous aliasing,
concurrent callbacks, normal/error/cancel cleanup, direct public emit, actual
engine eviction buffers, and the default DataManager budget registration.

A real pinned fork parser/normalizer, source revision journal, SQLite canonical
commit and durable delivery enqueue fault test proves source replay/persistence
and retry remain connected. This is separate from the synthetic cost harness.
Architecture and diff checks pass; the CI integration selector includes the new
owning tests. Native acceptance is being collected separately for this backend;
older package receipts do not qualify this changed revision.

Retained failures include the initial seven baseline accounting failures;
a test-harness weakref of a slotted BarState (corrected to a weakrefable existing
component-index container); and two local snapshot-fault tests that caught a
new deepcopy exception placed outside the old callback error boundary. The final
implementation restores that original boundary: source-backed copy faults are
retryable and ordinary faults retain the original log/continue behavior. No
production exception contract was relaxed to get a pass. The earlier 1,725-test
run predates those final two cases and is retained separately.

## Controlled same-input measurements

`measure.py PERIOD pending|callback` runs one fresh process with the default
DataManager owner registration and fresh SQLite. DataManager is not started;
its registered storage bridge remains inactive. Input components and source_ref
proofs are deterministic fixtures, not public-source qualification. Setup is
outside timings. Every successful callback's nine fields, initial full storage
payload hash and zero end reservations are checked in both versions.

| Components / held handoff | Baseline estimate / visible heap bytes | Product estimate / visible heap bytes |
| --- | ---: | ---: |
| 97 / pending source snapshot | 0 / 168 | 100,984 / 152,623 |
| 97 / suspended callback | 0 / 168 | 309,408 / 110,778 |
| 10007 / pending source snapshot | 0 / 168 | 10,248,824 / 15,145,498 |
| 10007 / suspended callback | 0 / 168 | 30,758,048 / 10,258,413 |

After acknowledgment/completion, the product returns to 128 estimated / 368
visible bytes (two empty registered dictionaries); baseline reports 0 / 168.
These increases mean previously omitted live graphs became visible, not that
physical allocation fell or rose by the displayed heap difference.

**The fixed 1024-byte component weight underestimates the pending source-proof
graph in these cases.** Multiple callback state indexes can instead overestimate
shared leaves. Byte-weight calibration, a trustworthy admission bound and joint
resource qualification remain original #126/#129 gaps. These measurements do not
prove the configured cap bounds actual heap or RSS.

Timed explicit publication includes unchanged callback copies and the inactive
bridge; it excludes state construction and diagnostic traversal. Three sequential
fresh-process pairs (initial baseline-first; repeats product-first) show 97m
pending CPU P50 baseline/product microseconds 658/853.5, 629/710, 699/704.5;
10007m callback 1658/1921, 1726.5/1792, 2010.5/2142.5. Tracking has overhead;
variability does not justify a stable performance pass. All P95/P99, GC stats,
whole-process peak RSS, source hashes and raw measurement results are retained
in `measurements.json`. RSS is not attributed to aggregation. No input/events,
quality proof or supported correction window is reduced between variants.

```sh
CANDLE_DATA_DIR="$PWD/output/handoff-tests" PYTHONPATH=backend python docs/qa/realtime-handoff-accounting-126-20261112/run-regression.py
PYTHONPATH=/scratch/full-baseline/backend python -m pytest docs/qa/realtime-handoff-accounting-126-20261112/retry_probe.py -q
PYTHONPATH=backend python -m pytest docs/qa/realtime-handoff-accounting-126-20261112/retry_probe.py -q
PYTHONPATH=backend python docs/qa/realtime-handoff-accounting-126-20261112/measure.py 10007 pending
```

The original completion criteria still govern on-demand preview/barriers,
retention/reconstruction, mixed prefix/tail integration, complete writer/read
inventory, continuous-load/performance and applicable indicator/strategy/native
matrices. This change alone does not establish those results.

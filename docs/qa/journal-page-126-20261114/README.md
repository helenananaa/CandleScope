# Durable delivery page/count read

Baseline runtime: PR #406 head `4603e2d9ad048c389a8da49661c1ff2692a4a36d`, now main merge `0f8ee5229a872b9a47447a528e189bb53078c3b4`. Candidate implementation: `38b2e87fab7bd895f1ba24891b9f35273a5a9b86`; `5bf7c45e912669411da67fd490ac4eebbda84712` adds only the late-enqueue contract. This batch consumes the existing #126/#129 durable delivery owner. Their parent acceptance matrices remain in force.

## Change and ownership

The original dispatcher reads a finite pending page and its diagnostic exact count on separate SQLite connections. Its explicit `flush_pending` barrier then opens a third connection to prove the post-dispatch empty boundary. Physical worker profiling and unprofiled phase measurements identified this repeated connection work; ordinary forming product ingestion does not itself call that explicit barrier on every frame.

The existing journal now optionally returns its page and exact count from one pinned SQLite view. Count is read before payload decoding. The page is admitted at one to 64 records. The dispatcher registers the returned page under its original retained-payload owner and continues original per-receipt canonical arbitration, publication, acknowledgement batching and fault recovery. The final fresh post-dispatch empty-boundary check remains a separate read. Empty barriers use two connections instead of three; no cached emptiness, pool, data cache, writer, queue or timer is added.

Explicit/custom pending and count readers retain their old independent calls, including subclasses and instance overrides. Journals without this optional interface use the existing fallback. The new snapshot grants no canonical or delete permission and never acknowledges a receipt.

## Contract evidence

Eleven new contracts cover the actual default DataManager empty-barrier physical read bound; coherent finite page/count under a concurrent acknowledgement; independent decoded result ownership; invalid/unbounded limits; both custom-reader overrides; a page decode failure followed by exactly one recovered canonical/publication result; cancellation that drains the original physical worker, releases the dispatcher and leaves the receipt unacknowledged for retry; and a receipt enqueued after an empty snapshot that must still be found, committed and delivered before the barrier returns. Existing acknowledgement, rollback, revision/deletion fencing and handoff contracts remain active.

The unmodified complete backend opens three connections and fails the new empty-barrier physical read bound. Candidate focused regression: **94 passed / 5 warnings, 8.63s**. Complete pinned-fork integration passes **2388 tests / 66 warnings, 347.93s** on the candidate runtime before adding the late-enqueue contract; all 11 new contracts then pass together in 2.92s. Architecture and undefined-name checks pass. Exact delivered-head/base CI must include all 2389 cases before main merge.

Retained fixture/tool failures are explicit: the first concurrent acknowledgement fixture attempted to acknowledge a still-pending receipt, which correctly does nothing; the corrected fixture first commits the receipt. A pinned offline Ruff version was unavailable in the local cache; the already cached executable passed. These are not product failures. All original output remains intact.

## Same-input controlled cost

Three alternating independent full-backend process pairs, 500 source-only forming updates at 2048m and 10007m, real SQLite/default DataManager/bus, original preview scheduler/throttle, final deadline included. Prefix seeding is outside timing. Pre-loop GC is reported separately; automatic GC remains enabled. No other local tests or native apps from this task ran during the measurements. All paired final forming projections, actual consumer events and accepted/computed/published watermark hashes match. The historical JSON key `canonical_sha256` hashes the forming projection; native and target canonical tables are explicitly empty in the cost harness. Actual canonical behavior is tested separately above.

| Slots | Explicit per-input barrier CPU ms baseline → candidate | Ingest CPU ms | Source admission + ingest + explicit barrier CPU ms |
| --- | --- | --- | --- |
| 2048 | 2018.503 → 1354.221 | 1041.692 → 1023.387 | 3861.435 → 3163.644 |
| 10007 | 2016.784 → 1376.189 | 1048.505 → 1057.040 | 3857.843 → 3229.893 |

The measured barrier CPU decreases about 32%; the deliberately barrier-inclusive harness total decreases 16–18%. Ingest CPU is neutral within these samples. This is not an overall product CPU improvement claim: ordinary forming ingestion does not run that barrier per input. It is not percentile, native, whole-application RSS/GC or cross-target workload qualification. The original #126/#127/#129 resource/native/consumer matrices remain open.

Reproduce with `run-paired-cost.py --baseline <complete-baseline-repo> --candidate <complete-candidate-repo> --output <new-output> --python <qualified-python>`, using the qualified plugin environment. Raw trials, source hashes, assertions and warnings are retained. The `ci-406-*` logs belong to the baseline PR #406, not the candidate.

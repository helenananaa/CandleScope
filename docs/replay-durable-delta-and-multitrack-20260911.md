# Durable checkpoint deltas and ordered multi-track batches

The subsequent [shared-history and screened-tape work](replay-shared-history-and-screened-tape-20260911.md)
reduces snapshot/delta construction overhead and extends eligibility to screened
resting orders and constant-valuation ONE_WAY positions. Measurements below describe
the earlier stage.

This completes the production connections that were deliberately absent from
the earlier hot-path repair. It supersedes that document's checkpoint-storage
and tape-batching status, not its compatibility and financial boundaries.

## Checkpoint storage

Adapter schema 5 adds `replay_checkpoint_base` and
`replay_checkpoint_delta_ref`. Existing schema 4 databases upgrade additively;
their full checkpoints remain readable without being rewritten. Actor and
review-anchor interfaces still receive self-contained v1 bytes.

The actual SQLite checkpoint writer computes a structural delta before inserting
the payload. A full base is retained separately, normally rotating every 16
eligible writes. A delta points directly to a full base, never another delta.
Small checkpoints and deltas without enough byte savings remain full. Publication,
references, base rotation and pruning are in the same transaction. Cleanup keeps
referenced bases plus the active base; session deletion removes the ownership
graph. Funding receipts are explicitly removed before their position legs because
their pre-existing foreign key lacks a delete cascade.

Recovery resolves and verifies base and target checksums. Corrupt dependent deltas
are skipped using the existing full-checkpoint fallback and command replay path.
Review anchors are materialized before export, so they remain decodable after
checkpoint/base pruning. Codec representation must remain byte-compatible for
stored delta targets; a future codec change requires a versioned reader.

This reduces durable checkpoint storage, not the complexity of creating the
actor's full logical snapshot. Delta construction still compares history-sized
data. No claim of constant-time checkpoint generation is made.

## Multi-track and tape execution

The real `TrainingRunService` coordinator now uses bounded final-state delivery
for eligible flat tape accounts under the existing
`REPLAY_FAST_FORWARD_OPTIMIZATION_ENABLED` switch. Open orders/positions and
account, book or funding dependencies retain their precise fallback.

Independent flat tracks can have different source timestamp grids. Planning
chooses a shared time boundary and trims each track by time, preserves each
source-sequence target, and records the original global event ordering. The last
tape event goes through the existing deferred-terminal step; sources are finalized
only at the immutable run boundary. No independent-broker event-count loop is used.

## Measured evidence

All workloads below are synthetic fixtures through the actual service, not live
archives or browser click-to-paint measurements.

Checkpoint A/B (`python -m scripts.replay_checkpoint_delta_benchmark --output ...`
from `backend`), 40 speed-control commands after identical setup:

| Measure | Full storage | Delta storage |
| --- | ---: | ---: |
| Checkpoint plus newly created base BLOB bytes written | 388,000 | 50,150 |
| Retained checkpoint plus base bytes | 314,754 | 56,913 |
| Median command latency, instrumented | 10.886 ms | 10.573 ms |
| p95 command latency, instrumented | 16.600 ms | 15.322 ms |

Final state hashes matched. BLOB writes decreased about 87%; this excludes other
tables, indexes and WAL amplification. Latency varied between runs; no repeatable command-latency improvement is claimed.
Receipt: `output/replay-checkpoint-delta-20260911-final.json`.

Two-track tape A/B compares final per-track components/cursors and every global
event's timestamp, phase, track and source sequence:

| Timestamp grids / target | Adapter advances: fast / reference | Observed ms: fast / reference |
| --- | ---: | ---: |
| Aligned / partial range | 4 / 14 | 65.640 / 126.044 |
| 200 ms offset / partial range | 6 / 26 | 89.319 / 177.072 |
| Aligned / source terminal | 4 / 14 | 59.997 / 157.565 |
| 200 ms offset / source terminal | 6 / 26 | 97.887 / 199.717 |

Receipt: `output/replay-multitrack-batch-20260911.xml`. A separate waiting-order
case confirms optimization enabled still takes the scalar path and matches the
reference. These timings are individual observations, not percentile guarantees.

## Validation and deployment boundary

The broader backend run passed 121 tests in 166.13 seconds. Subsequent delta and
contract tests passed 38 cases, including a new boolean/integer representation
case and the updated storage-table golden. Five multi-track cases pass; the
TypeScript contract suite passes 23 tests. Focused delta tests cover v4 migration,
reference retention, independent review decoding, restart, corruption fallback,
rollback after actual delta insertion and archive deletion.

Initial probes exposed an obsolete test API, an out-of-range target one millisecond
past the fixture terminal, missing deferred-terminal handling in the new batch
path, and a funding-receipt deletion foreign key. These were fixed or corrected
without relaxing financial/global-order equality. The first checkpoint benchmark
used unsupported speed 2; the recorded workload uses supported speeds 1 and 5.

No live database was migrated and no service was restarted. Existing optimization
switch defaults are unchanged. Rollback after a database upgrade requires the
pre-upgrade backup; old code cannot read schema 5 deltas. No commit or push has
been performed for this follow-up.

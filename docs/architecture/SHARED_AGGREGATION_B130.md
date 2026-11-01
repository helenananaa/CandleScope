# B130: bounded shared aggregation blocks

Stage 130-C of [#130](https://github.com/helenananaa/CandleScope/issues/130),
consuming D126 and the K130 contract merged by #173 at
`d85bcf392503140ab46500cfdd45f2de62799d44`.

## Ownership and qualification

`DataManager.shared_blocks` is the single process-local block owner. It stores
immutable K130 summaries, not another canonical BarData copy, writer, download
service, persisted revision log, historical planner or realtime initializer.
The existing history executor, acquisition fences, materialization registry and
durable delivery remain responsible for their current work.

A `BlockKey` carries the complete source `SeriesKey` (including interval/basis,
provider/venue and field/session semantics), actual half-open range, algorithm
version, and an optional bounded accepted-input fingerprint. It has no consuming
target interval. A block's K130 `target` field names this source basis; consumers
compose summaries and evaluate the actual requested target range. The separate
monotonic block version identifies an immutable value inside this manager only.
It is not a durable revision, publication watermark or proof of persistence.

The initial production adapter covers existing fixed-epoch custom history with
a source of at least one hour and an integral target/source ratio of 2–64.
Complete, contiguous, closed and trusted buckets use aligned two-leaf blocks,
so 2d/4d/5d and other qualified targets reuse the same source work. Single-leaf
edges compose directly with K130. Calendar/session, large, missing, untrusted,
forming and duplicate-source buckets retain their established executor. The
manager itself accepts bounded calendar/irregular summaries with actual ranges;
calendar planning and broader source qualification remain with H127.

Legacy query inputs can include accepted in-memory immutable bars as well as
canonical stored rows. Their complete normalized values and source quality are
digested into the block key, in addition to the durable view token. A changed
snapshot cannot reuse a previous value merely because SQLite has not changed.
Blocks retain summaries/digests, not their original leaf lists. Non-default
derived identities remain rejected by the existing query route; the manager's
key/API independently isolates the full identity for future consumers.

## Read view and lease protocol

```python
with manager.view((source_key,)) as view:
    # Acquire inputs within this source view, or use a D126 acquisition floor.
    with manager.acquire(block_key, view, build_summary) as block:
        output = consume(block.summary)
# Publish output only after successful view exit.
```

The view reads versioned source evidence before work and revalidates it on exit.
An acquisition floor is required when the legacy adapter already has decoded
inputs; a source changed since that floor is rejected. Changed, failed, reset,
rebound or closed views cannot publish successful results. Existing immutable
values are historical snapshots; holding a raw object after lease/view expiry
does not grant current-source or persisted/adopted authority.

Each lease pins a value against LRU eviction. Invalidated pinned values move to
retired storage, remain fully charged, and reject subsequent lease access.
Closing the last lease frees a retired value. Lease close is idempotent; view
exit releases any remaining leases on success, failure or cancellation. New
views and leases are bounded. There is no indefinite per-consumer subscription
or tombstone dictionary. A caller retaining output references after its lease
owns and must account for those references in its own resource scope.

`acquire(key, view)` with no builder is a cache-only API: a miss returns `None`
without I/O, building or joining. This permits a realtime consumer to use the
same manager rather than introducing another shared cache. R129 still owns its
incremental state, asynchronous admission and confirmed/overlay handoff.

## Build deduplication and cancellation

Only identical source identity, range, algorithm, accepted-input fingerprint
and full revision vector join a flight. Different views never accidentally
share a result. One pure synchronous callback runs on the initiating worker;
joiners wait outside locks. The manager does not submit nested storage work or
hold locks across source I/O, a builder or a wait. Builders must not perform I/O,
wait on another executor, or introduce cyclic build dependencies; joining the
same flight from its own builder is rejected rather than deadlocked.

A per-consumer cancellation event releases only that participant. An owner
already computing can finish the bounded shared work for other participants;
the cancelled consumer receives no lease. Failures settle the flight and permit
a fresh retry. Futures contain bounded error records rather than shared
tracebacks retaining acquired pages. A closed/reset/invalidated generation
rejects late builders before cache adoption. Closing an owner fences all work;
reopening requires its previous views, leases and builders to drain.

## Revision consumption and invalidation

`DurableBlockRevisions` reads the existing D126 `RevisionStore` and creates no
new ledger. `read_versions` supplies per-series committed-content view tokens
from one transaction, including deletion of an empty range. These tokens are
stable across unrelated series commits. The global acquisition permission
floor remains separate. A unique adapter domain separates process/storage
binding lifetimes; different domains are retained, never numerically ordered.

The dependency index maps `(series, domain)` to bounded retained blocks. Parent
summaries carry flattened source dependencies, so a source change invalidates
both children and composed parents. D126 change ranges are conservative,
coalesced envelopes: its adapter invalidates the entire reported series rather
than pretending they are an exact edit log. The public memory-source API can
apply an explicit half-open range. Duplicate observations with the same token
are harmless. The existing DataManager revision loop also polls this consumer,
so cache invalidation does not depend on another historical query arriving.

A D126 overrun/reset or a revision-read failure invalidates all reusable blocks
and active views. No old result is served as current during recovery. A later
successful read can rebuild. Reverse-index entries disappear with their last
block; there is no independent unbounded history of observed source versions.
Database changes by another process are observed through D126; cache ownership
and memory accounting remain per manager/process, not distributed sharing.

## Resource admission

Default limits are 16 MiB, 1,024 total cached/retired blocks, 8 concurrent
flights, 64 views, 256 leases, 16 source dependencies per view and 128 occupied
ranges per summary. All limits reject or defer further admission; active pins
are never evicted to disguise pressure. The same D126 `MemoryBudget` registers
`aggregation-blocks` alongside history, realtime, cache and delivery owners.

Views, leases, dependency/index metadata and retained summaries are charged.
Each flight reserves an explicit working allowance plus its control metadata;
the builder must fit its temporary work into that allowance. The initial
adapter only builds two accepted leaves, with a 16 KiB work allowance.
Input pages and final query outputs remain charged to their existing owners.

`MemoryReservation.retain` atomically replaces working admission with retained
usage under D126's budget lock. This avoids either a double charge or an
unaccounted handoff that concurrent owners could oversubscribe. Usage callbacks
are cheap lock-free snapshots, avoiding a manager/budget lock inversion. Heap
traversal is performed only at block creation or on explicit diagnostics, never
on every cache hit or market tick. Estimates are conservative Python-value
accounting, not an RSS/allocator or external-runtime memory guarantee.

Capacity exhaustion in the initial history adapter falls back to the existing
bounded pure reducer under the outer D126 acquisition fence. Revision failure
does not take that fallback: it produces a retryable unavailable/pending result.
`collect()` removes only unleased reusable blocks. Shutdown, source rebind and
retention never delete canonical data, durable revisions or deletion evidence.

## Acceptance and next interfaces

Contract tests cover immutable identity, exact domain/view separation, field
and closure parity, leap-month actual ends, unknown/partial/forming fallback,
parent dependency propagation, singleflight races, consumer/owner cancellation,
failure retry, late result rejection, capacity and retired-value accounting.
SQLite integration covers committed amendment/delete/empty-delete, rollback,
external-process writes, background adoption, rebind/restart, real streaming
queries and the existing materialization owner. Native and resource receipts
are recorded separately against the final source commit.

This stage delivers B130 with a narrow production consumer. It does not claim
H127's complete mixed-source planning, R129's incremental/preview consumer, or
J's historical-prefix/overlay state machine is finished. Those consumers must
use these views, revisions, leases and resource admission rather than duplicate
the facilities. No general CPU improvement is assumed; same-input measurements
and native behavior determine the qualified scope.

Rollback reverts this stage and rebuilds transient blocks from the existing
canonical storage. There is no new persisted block format or second write path.
Keep D126 revision, deletion and delivery receipts intact.

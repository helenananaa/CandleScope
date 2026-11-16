# D126 v1: K-line ownership, revisions and memory admission

This PR provides the #126 consistency interface on top of `b84b5e3` and native
read fencing from `40f789bf`. It is a stage delivery for #126/#130/#127/#129,
not a claim that the four owners have completed joint acceptance. The production
writer remains the SQLite repository / existing BarDeliveryJournal. There is no
second real-time journal or aggregation executor.

## Published values and readers

| Boundary | Contract |
| --- | --- |
| BarData, cache latest/range/before/get_bar_at, QueryResult bars | Frozen, slotted scalar value; containers belong to the reader. Copies safely share the immutable record. Computed fields are initialized before publication. |
| Custom-query singleflight | Clones result containers and nested metadata/proof/exclusions; shares immutable bars. |
| DataEventBus | Owns a detached envelope; each subscriber gets independent metadata/envelopes and shared immutable bars. |
| Aggregator latest/active/recent/bucket reads and publisher | Detached BarState/event; copies the component index and shares immutable ReadonlyFields components. A later builder update cannot change an old snapshot. |
| Aggregator get_pipeline/get_bar_state | Owner/maintenance management hooks, deliberately mutable; not ordinary query interfaces. |
| Indicator synthetic input | Constructs a new BarData with transformed fields; never edits a published bar. |

ReadonlyFields is only an ownership utility. It does not define
AcceptedComponent/AggregateSummary or duplicate #130 semantics. Its values must
already be immutable. Existing enhanced-field availability, quality arbitration,
finality, forming-only data and cache-only intervals retain their contracts.

## Revision domain and changes

`KlinesRepoAdapter.revision_store` exposes:

- `head() -> int`: database-wide monotonic revision; unrelated series may advance it.
- `changes_since(cursor, limit=4096) -> {revision, reset, changes}`: head and changes
  read in one SQLite transaction. Each change identifies exchange, market_type,
  symbol, interval, provider_id, venue, asset_class, series_variant,
  price_adjustment, session_variant and volume_semantics, with revision,
  delete_revision, conservative start_ms/end_ms and the latest operation.
- `acquisition(owner=None, revision=None)`: capture before fetching/building.
  Use `acquisition_scope(scope)` around supported writes. The revision argument
  is a persistent **deletion floor**, while newly acquired inputs use the current
  head. Jobs resumed after a deletion must not silently receive new permission.

SQLite triggers update data and revisions atomically, including raw SQL from a
separate process. A rollback advances neither. Identical logical upserts and
updated_at-only changes do not advance the data revision. Changing series
identity/open_time in place is rejected; use delete plus insert.

Changes are coalesced to one durable row per semantic series, including a retained
delete watermark. The table grows with distinct historical identities, not with
the number of writes. This is **not** an individual-event log: invalidate the
reported series, not merely its latest operation. On `reset`, discard the
consumer projection and adopt the supplied head. A slow consumer never relies on
an unbounded process-local callback backlog. Do not delete revision rows as GC:
that would remove deletion protection. A future identity-tombstone compactor
needs an epoch/reset protocol before it can safely remove them.

A cache has one CacheRevisionConsumer. It polls on a 50 ms schedule in the running
DataManager; reads also poll when due. Scheduling and SQLite availability can
extend elapsed observation age, which is exposed in diagnostics. Failed adoption
keeps the cursor unchanged; the worker retries, and reads that cannot validate
return pending. The recent conflict index is bounded to 4096 entries; overrun
forces conservative conflict handling.

`query`, `query_before`, `query_latest`, and GET `/klines` accept `min_revision`.
A supported read forces adoption, then returns a stable result with
`metadata.storage_revision >= min_revision`, or an empty pending/retryable result
when that revision is not available. This is a nonblocking contract, not a wait
until timeout and not a promise that no later commit can occur. An unsupported
adapter/cache-only interval returns `revision_unsupported`. Ordinary complete
cache hits have scheduled observation; storage/derived reads validate before
publication. Conflicts never trigger an automatic write just to satisfy a token.

## Physical writer inventory

| Writer / route | Transaction and post-commit contract |
| --- | --- |
| CLOSED/AMENDED via AggregatorBridge | Builder captures acquisition revision before inputs; existing journal persists it. Commit checks target revisions, and derived results check their semantic family. Ordered journal predecessors are allowed; newer external edits/deletes reject old receipts. Publication rereads canonical data through cache adoption. |
| REST/backfill, coordinator queue/retry | Capture acquisition before source work; request merging keeps the oldest deletion floor. guarded_write checks in the same BEGIN IMMEDIATE transaction as upsert. Successful own batches advance only the active scope's accepted revisions. |
| History archive import/revision | Same guarded transaction for rows, import receipt and invalidation. Existing archive lifecycle remains separate. |
| Custom materialization | Query captures a scope before source reads; own accepted commits are distinguished from competing edits. Register derived identity before writing. |
| Manual history | Job creation records a durable deletion floor; resume reacquires input at a fresh head but preserves that floor. Terminal jobs release their acquisition record. Materialized source is explicitly manual_history_derived. |
| Settings recomputation / replace | Capture revision before reading inputs; replace_bars atomically checks, deletes, marks the deletion and writes replacement. Failure restores both rows and revision. |
| Explicit delete, including an empty range | Records a deletion revision even when no physical row existed. Existing cancellation drain/final invalidation stays in place. |
| Retention / storage GC | Every physical deletion records revisions. Retention transaction mode suppresses deletion of independent materialized histories; their own protection/retention policy still applies. |
| Offline kline_repair | Existing stopped-app, fingerprint and transaction rules remain; initialized SQLite triggers record its writes. It is not an online acquisition executor. |
| Schema migration | Runs before publication. Additive revision/receipt columns and triggers; existing rows become the initial canonical view. |

`check_architecture.py` rejects ordinary literal/f-string K-line SQL mutations
outside the three reviewed storage owners. This is a static inventory check,
not protection against arbitrary dynamically generated SQL. Triggers observe
external writes; fencing their *intent* requires the supported acquisition
protocol. Pre-D126 binaries are not safe concurrent writers.

The current dependency fallback is conservative: changed families invalidate
resident durable caches, and native changes remove overlapping registered
materializations. Known derived provenance is seeded at migration. It does not
infer ambiguous older rows mislabeled as a native exchange, nor implement #130's
block dependency graph. #130 must register its materializations and consume the
same changes/reset contract instead of creating another revision ledger.

Source-recovery watches preserve their deletion floor. Obsolete watches are
retired without fetching; new windows can establish fresh watches. Pending
receipts survive process exit and cannot resurrect a deleted series. An
unversioned late backfill notification is only a hint to reread canonical rows.

A native receipt may commit after a newer mutation only when its complete candle
range is disjoint from the durable, lifetime-coalesced mutation range, or the
existing ordered-predecessor rule applies. This permits the next natural close
after older missing bars are repaired. It does not advance the receipt's
acquisition revision. Overlapping edits, empty/full-range deletes and uncertain
derived dependencies still require the original fence/recovery path; a later
disjoint edit cannot hide an earlier overlapping mutation.

Revision-rejected receipts also persist `bar_delivery.recovery_required=1` in
the rejection transaction. They remain in the bounded pending/admission count
and cannot be pruned until the dispatcher marks matching bar subscriptions
terminal with `source_revision_superseded` and acknowledges that handoff.
Callback notifications run separately; iterators fail without waiting for another
bar. The handoff is idempotent per subscription, including after an acknowledgement
retry. Quality-rank rejection alone does not request recovery. A canonical row
deleted after commit or before adoption follows the same snapshot-required path;
the rejected/deleted payload is never published or written back.

Initialization adds this column with zero for existing records. It does not infer
missing notifications for previously terminal receipts. Restart consumers with a
fresh canonical snapshot when upgrading; do not run older writable dispatchers
alongside pending recovery handoffs because they do not preserve the new marker.
Strict and gap-aware bar consumers both resnapshot/re-subscribe after this terminal
delivery failure; an ordinary source gap still follows its selected policy.

## Shared memory contract

`DataManager.memory_budget` registers bar-cache, realtime-state, event-delivery,
history-query, history-backfill and durable-delivery. Defaults: 256 MiB total;
respectively 128/128/32/64/64/16 MiB owner limits. Aggregator subscriber snapshots
and in-flight durable payloads are included in their owners; durable rows remaining
on disk are not counted as resident memory. Set DataManagerConfig memory_budget_bytes and
memory_owner_budgets to tune them. Owner limits share the total, not additional
independent allowances.

Consumers register cheap `usage()` counters and optional `roots()` diagnostics,
then use `with budget.reserve(owner, bytes_needed)` for work admission. Reservations
release on success, error and cancellation. Active leases prevent unregistering.
Deep queries reserve an estimated output/work allowance; backfill reserves its
planned work allowance. Exhaustion returns a retryable/deferred state rather than
removing active data. BarCache GC includes common byte pressure, retains existing
generation/access checks and active/subscribed protections, and exposes degraded
protected memory when nothing safe can be removed. Durable receipts are not
memory-GC victims.

`snapshot(measure_heap=True)` traverses registered Python values once by object
identity. Per-owner unique bytes are attributed in registration order; sum them
for the deduplicated total. This is an opt-in diagnostic, not a tick operation.
Estimates include scalar/container overhead but are not a hard RSS cap. The roots
exclude allocator fragmentation, native memory and unregistered transient work.
#127 must register/limit streaming buffers and outputs; #129 owns state retention
and reconstruction; #130 owns block leases/dependency retention. Their minimum
consumer integration receipts and joint budget acceptance remain separate work.

R129 default source dispatch shares only a recursively immutable component value
among compatible default derived targets. Target admission, indexes, finality and
revision handling remain independent. Nested source references are captured before
publication; mutable caller payloads cannot change accepted values. Preparation
holds at most one latest value per dispatch, at most 128 target handles, and uses
the existing realtime-state budget for up to 64 reusable 16 KiB work allowances.
Capacity is an estimate, distinct from physical heap; no source values persist in
the allowance pool. Cancellation releases task-local values; detach, rollback and
stop trim idle allowance. Optional admission failure uses independent preparation.
`BAR_AGG_SHARED_COMPONENT_INPUTS=false` disables sharing while preserving ownership
and revision fixes. Custom extension routes remain independent.

Heap diagnostics retain temporary root views across all owners so identity-based
deduplication cannot hide a later owner's graph through recycled container IDs.
Ordinary estimates count accepted immutable component/proof reference weights
and may overcount shared values. Foreign mutable entries use live traversal;
consumer-mutable callback proofs are measured while their frame owns them.
These estimates remain distinct from allocator/RSS bounds. See
[component weights](../qa/component-byte-accounting-126-20261113/README.md) and
[callback proof accounting](../qa/callback-proof-accounting-126-20261113/README.md).

Realtime-state also owns closed/expired engine eviction buffers, pending source
publication snapshots and suspended publisher input/dispatch/callback/retry frames.
The publisher tracks existing payload references until the frame finishes; normal
completion, failure and cancellation release registrations. Retry snapshots retain
the existing delivery IDs; retries enumerate IDs and release each acknowledged
payload before advancing. Per-state identity deduplication avoids alias double
charging; opt-in roots include the actual private dictionaries and buffers.
This accounting does not discard data or raise budgets. See
[handoff accounting evidence and limits](../qa/realtime-handoff-accounting-126-20261112/README.md).

Eviction drains claim one raw buffer item synchronously before awaiting the
existing public emitter. Per-pipeline claims remain in realtime-state roots until
completion. A task-context observation marks transfer to the existing publisher
source snapshot before callbacks await. The inherited context contains only a
numeric identity and flags, deactivated on scope exit; no payload or callback is
retained by child contexts. Failure/cancel restores raw data only
before transfer, even when a concurrent retry already acknowledged the snapshot.
No-source/pre-transfer failures retain their original retryable buffer item.
Silent drains cannot discard another task's claim. Successful items release
before later callbacks; no callback lock or independent delivery ledger is added.
See [eviction handoff proof and costs](../qa/realtime-eviction-handoff-129-20261113/README.md).

### H127 page receipts

The default coordinator uses an explicit `run_receipt()` contract for qualified
native REST plans. The fetcher awaits the existing reconciler/writer per page
before dropping the page. A receipt counts unique fetched rows, not successful
commits; `ReconcileResult` owns committed counts/ranges. Mixed plans then consume
the existing canonical H127 stream/K130/D126 path. Ordinary `run()/fetch()`,
payload observers, preview, archives and unqualified/custom routes retain their
complete payload contracts. Register new payload observers between active receipt
runs; the explicit receipt API rejects registrations while its payload contract
is frozen. Ordinary calls retain dynamic registration.

Page/dedup/output diagnostics have bounds, use the existing history-backfill
budget, and retain source, deletion, revision and owner fences. The conservative
whole-window forecast remains and page reservations are additional. Archive
objects retain their atomic import contract; this is not universal archive
streaming or whole-application constant memory. See
[receipt scope, failure evidence and costs](../qa/history-fetch-stream-127-20261113/README.md).

### R129 deferred component previews

An accepted fixed-grid forming tail can advance the existing immutable component
index before its K130 summary/projection is calculated. Every input still passes
freshness admission against the immediately preceding accepted value. Only
repeated replacements of the same eligible forming tail coalesce; close,
correction, new-component/bucket and custom execution paths calculate eagerly.
Native snapshots, price-only and trade/tick inputs retain their execution modes.

One aggregation-loop scheduler owns at most 128 pending/in-flight references,
with a single deadline handle and at most 16 entries per drain. Each entry reserves
16 KiB under realtime-state, covering metadata and its extra prior immutable
tail (qualified at <=8 KiB). It copies no source history. The original publisher
still owns fanout, throttling, source retry and delivery. Existing publications
wake delayed work on completion, avoiding concurrent duplicate previews and
retention of finished builders across later awaits. Detached in-flight builders
remain visible to the same memory owner. Failure/cancel/detach/stop drain leases;
capacity/admission failure uses eager calculation with explicit fallback diagnostics.

Effective `preserve_updates` demand bypasses calculation coalescing, as it already
bypasses producer throttling. Producer flags remain authoritative. Disabled
UPDATED output may retain dirty state without a timer; reads and mandatory
barriers still materialize it. Public state copies, scalar adapters and storage
conversion calculate the latest accepted value before returning. Diagnostics do
not force calculation. Deadline publication reuses the target token and existing
H127 source validation/owner locking; it cannot revive deleted or rebound work.

Native source receipts use the existing storage owner to recheck at most 256
accepted leaves in one read transaction before a delayed publication. Each
immutable leaf is at most 8 KiB; history-query reserves its retained bytes plus
16 KiB until the physical read finishes. Current journal heads and canonical
closed values (including warm-start leaves without receipts), deletion floors
and the target revision must agree. Normal superseding source observations skip
the old preview without requesting repair; canonical changes use existing
recovery. Input-version, target-generation and owner checks reject late reads.
Larger/unqualified receipt windows retain eager execution. This is a bounded
read view, not another journal, writer or source cache.

The watermarks are builder-local ordinals: `preview_input_version` counts accepted
target observations (including prefix adoption), `preview_computed_version` marks
their projected values, and `preview_published_version` marks successful publisher
fanout for that builder. They are not transport sequences, database revisions,
nor consumer acknowledgments. Accepted/computed/published lag and fallback reasons
are exposed in bounded read-only diagnostics. Journal retries retain their existing
payload/delivery ownership; these counters do not replace durable delivery receipts.

`BAR_AGG_DEFERRED_COMPONENT_PREVIEWS=false` selects eager calculation. Pending
work remains fenced and can be drained; rollback does not remove canonical rows,
receipts, revisions, recovery evidence or supported runtimes. Started default
component pipelines consume this stage; unsupported grids/strategies retain
their original algorithms. Whole-runtime load, closed/no-prefix state retention,
all consumer policies and the remaining #129 matrix require separate qualification.

### R129 closed component retention and canonical recovery

Closed authoritative default COMPONENT buckets can replace their raw indexes
with the existing immutable H127 prefix, including buckets that never had a
warm-start prefix. Fixed native source grids, complete elapsed coverage and the
existing 65536-source-slot bound remain required. Every retiring leaf is compared
against trusted canonical data in pages of at most 128, followed by the original
K130 projection check. Equal aggregate totals cannot hide opposite leaf changes.
Status, finality, close reason, timestamps, watermarks and deletion permission
floors survive optional compaction. No synthetic event or canonical write occurs.

The existing H127 runtime owns at most 128 maintenance IDs/epochs/source names,
charged at 1 KiB each to realtime-state. Its existing timeout loop drains one
job per pass, without a new timer or background task. Payloads stay in the closed
state index; physical work registers them with the existing publisher retention
owner and reserves the old frozen index/proof graph plus bounded staging work.
Pages stage outside the target lock. A final durable/source/strategy/config/
builder/version/generation check and adoption use the existing target lock, so
new forming buckets can proceed during the expensive readback. Cancellation
waits for physical reads; detach clears queued metadata. Rejecting an obsolete
optional read must preserve newer jobs and prefixes for the same target.

Publisher completion can mean durable admission while the original dispatcher
still owns a native commit. Maintenance drains that dispatcher before canonical
staging. Covered closed inputs also drain it before deciding that a prefix is
unchanged. A changed, already-closed bucket rebuilds its complete canonical
window, consuming D126's existing canonical-recovery permission protocol: the
fresh read revision never replaces the old explicit-delete floor. Missing or
untrusted coverage revokes the old close instead of resurrecting accepted data.

`BAR_AGG_COMPACT_CLOSED_COMPONENTS=false` disables new optional maintenance;
existing compact prefixes retain mandatory revision validation and recovery.
Capacity, budget, field/grid/identity mismatch and stale reads preserve the old
indexes with bounded diagnostics. This decline path and the remaining state,
consumer/source, resource and long-running matrix still need qualification;
these bounds are not a claim that all application memory or RSS is bounded.

## Migration and operational rollback

1. Stop old writers and back up the SQLite database (including WAL through a
   supported SQLite backup/checkpoint flow). Initialize with the new version;
   initialization is idempotent. Existing pending journal/watch records start at
   revision zero; existing unfinished manual jobs receive a conservative zero
   deletion floor. No historical user data or QA evidence is removed.
2. Start with an empty process cache; durable changes reconstruct adoption. Watch
   revision age/errors, pending/rejected delivery, memory estimates/reservations
   and GC protection diagnostics. Failed adoption must not bypass validation.
3. To disable optional work, stop that consumer and release/drain its leases;
   preserve the data, revisions, acquisitions, receipts and deletion watermarks.
   Keep the revision-aware writer active. No shadow writer or duplicate publisher
   is introduced.
4. Downgrading to a pre-D126 **writable** binary is unsupported: it lacks
   acquisition fencing. Preserve the upgraded DB, use a read-only/export path or
   a forward fix. A pre-upgrade backup is a separate historical recovery copy,
   not permission to overwrite newer committed data. Full binary downgrade and
   desktop restart acceptance are not claimed by the component tests.

See [verification and measurements](../qa/issue126/D126_BACKEND_VERIFICATION.md).

### First live prefixes and deletion permission

A qualified default fixed-grid forming target with at least 2048 source slots may retire its first 128 confirmed live components through the existing H127/B130/D126 owner, even when startup admitted no history prefix. Closed and first-forming maintenance share the existing bounded metadata queue and timeout loop. Canonical staging runs outside the target lock; final validation must fence the exact retired immutable leaves, target generation, strategy/configuration/storage/budget bindings, and latest target projection. Concurrent forming-tail progress is allowed. Missing or changed evidence retains raw components with bounded diagnostics and progress-based retry; it does not establish a hard retention bound under failures.

Every history-prefix adoption preserves the builder's oldest explicit-delete permission floor separately from fresh canonical acquisition provenance. This includes warm re-adoption and retiring the last raw seam, not just source-revision recovery. A fresh source view cannot grant permission to recreate a target or base series explicitly deleted during the builder's lifetime. Existing D126 transaction checks enforce this distinction. See `docs/qa/realtime-forming-retention-129-20261113` for three full-old-backend SQLite resurrection regressions, bounded live handoff contracts, current native qualification, and retained costs/failures.

A native-first callback may return durable admission while the original dispatcher still owns commit. A newly closed component outside a compact prefix also changes that prefix's source-series revision. Closed-input validation/refresh therefore waits for the original dispatcher boundary before reading any retained prefix, rather than only for corrections inside it. `flush_pending` reuses the existing 64-receipt dispatch pages, within the existing history caller deadline; a single page is insufficient as a commit barrier. Errors or rebinding cannot be reported as an empty boundary. This does not turn forming previews into durable delivery or consumer acknowledgement.

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

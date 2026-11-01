# 129-A: single-target component increment and correction

This stage consumes K130 on main after B130/H127. It replaces repeated full
sorting/reduction for ordinary fixed-grid COMPONENT updates. It does not add
R129 shared source ownership, preview scheduling, window retention or H127
initialization. Those remain 129-B/C/D and J.

## Owner and execution

The existing BarStateEngine remains the sole mutable target owner. Source
identity, freshness sequence, D126 source revisions and authoritative-correction
admission are checked before updating the accumulator. Native SNAPSHOT,
PRICE_ONLY and tick INCREMENTAL modes retain their existing strategies.

Each eligible BarState holds a private ComponentAccumulator:

- A binary forest summarizes the accepted prefix in chronological runs.
- One replaceable tail represents the newest component.
- K130 FieldSummary/combine_fields own OHLCV/enhanced-field arithmetic;
  evaluate_coverage owns quality and explicit-finality decisions.
- Metadata tracks actual bounds, adjacency, positive width, first/last input,
  closure and count. Gaps, overlaps, crossing bounds or forming components
  cannot acquire authoritative closure merely because time has elapsed.

A same-position tail replacement recombines the prefix with the replacement;
it never subtracts cumulative fields or adds the new cumulative volume twice.
Normal forward append folds a binary carry and recomputes at most O(log n)
prefix runs. Tail update work is O(1), append work O(log n), and extra retained
execution metadata O(log n). Input normalization remains once per accepted
snapshot, and final projection uses the existing rounding/unknown-field rules.

Earlier corrections, out-of-order insertion, changed component bounds and
ambiguous equal-time ordering take a full sorted rebuild. Rebuild constructs
the forest using K130 batch reduction of disjoint runs, avoiding per-leaf
summary allocation. This path remains O(n log n) sorting/O(n) reduction and
temporary O(n) references; no constant-time historical-correction claim is made.
High/low reductions, volume reductions, changed open/close, unknown fields and
gap repair are recomputed from the authoritative accepted snapshots.

The common projection also fixes a prior failure on absent raw enhancements:
None no longer reaches round(). Only masked internal diagnostic counters use
zero; public/storage enhancements remain None and absent from enhanced_fields.

## Scope, retention and publication

The fast path requires parsed fixed-epoch target/source intervals and at most
65,536 accepted components. Unsupported/calendar inputs and larger buckets
retain batch reduction. This is a bound on the new index, not permission to
truncate source history or drop corrections. The existing source_snapshots map
and closed-state retention policy are unchanged; reducing those is 129-C.

The index is part of its BarState lifecycle, with no global registry, second
cache, revision ledger, lease owner or durable format. Expiry, removal, clear
and shutdown release it with that state. Source replacement discards stale
state through existing D126/recovery paths. Diagnostics add its conservative
estimated bytes to the existing aggregator owner; retained-size traversal sees
the dataclass and its summaries. This is not a new process RSS hard cap.

BarState.__deepcopy__ drops the mutable index. Published states, queued events
and public getters retain their existing detached component maps and immutable
values. A copied state reused as a builder reconstructs its own index. Existing
publication still copies the component dictionary; this cost is included in
the public-ingest benchmark and remains separate from reducer work.

Counters describe currently retained states: indexed states, appends, tail
replacements, rebuilds/rebuilt components, summary nodes and estimated bytes.
They are not lifetime counters after an owner evicts a state.

## Qualification and rollback

`test_component_incremental.py` compares each accepted step with the retained
batch executor, including shuffled input, holes/overlaps, old extremes, reduced
volume, unknown fields, repeated revisions, ties, snapshots, retained-memory
bounds and actual publisher close/amend order. A 10,007-component test forbids
sorting on repeated tail updates and validates full closure after the final
component closes.

The QA scripts separately measure state-executor work and the actual public
ingest/lifecycle/finalizer/publisher callback path, with equal inputs and equal
event counts. Recorded public daily inputs have an independent Decimal oracle.
See [the acceptance record](../qa/r129-20261101/README.md).

The bounded fast path defaults on. Set BAR_AGG_INCREMENTAL_COMPONENTS=false
before constructing/restarting the aggregator to use the batch path. Both
paths use the same admission and K130 semantics; the switch is internal, not a
new user-facing feature setting. No database migration or rollback of committed
revisions is involved. Native release qualification and later main integration
remain distinct from this development PR's local results.

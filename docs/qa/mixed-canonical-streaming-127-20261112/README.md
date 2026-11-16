# H127 qualified canonical-page streaming

Base: `30fe07760d3cf0e9b871dc13d9f7900baf277674` (PR #376).
Refs #127 / #126. Parent issues remain open. Product/source hashes and evidence
provenance are recorded alongside this report.

## Change and ownership

Qualified mixed backfill previously requested 256-row SQLite pages but appended
all pages/windows into a canonical row dictionary and then another reduction
list. The default reconciler now folds and releases each page before pulling the
next, retaining one target's sufficient statistics and bounded target outputs.
The existing 512-target / 16,384-source-row / 131,072-position request bounds and
outer history-backfill work admission remain; no global budget increases.

`ClosedKlineRowStream` is the ordered-page adapter for the existing strict stored
row policy. The batch `aggregate_kline_rows` helper delegates to that same policy;
it still accepts unordered batch input and avoids a duplicate full-size index.
K130 owns field normalization, sums, coverage/finality projection and final-only
rounding. No new cache, downloader, persistent writer or revision ledger is added.
Canonical paging, planning, source authority and D126 materialization ownership
remain with their existing owners. The unused collecting bounded-reader branch
was removed; unqualified/custom-aggregator batch contracts remain explicit.

Same-source duplicate/adjacent windows coalesce before reads; overlapping source
grids are rejected. Every page checks full source identity, integer/range/order
and page/total row limits. Bad close/grid/fields cannot prove a target; missing
or untrusted rows leave their actual gap. All pages complete before any target
materialization, and the original D126 acquisition/computation fingerprint guards
remain. Cancellation drains already-running bounded preparation/storage workers
through the existing executor contract before releasing work ownership.

## Qualification cost correction

The first stream implementation ran the complete owner/calendar/source
qualification twice per page. Profiling identified 175 full binding validations
and 178 composition declarations in the 16-target case, accounting for nearly
all additional reconcile CPU. No target had been published during these reads.

Final code performs cheap config/owner/planner/resolver/storage/rollout checks
between tentative pages, while retaining the **full** calendar/source qualification
before reads start and again before materialization. The same final proof still
rejects a qualification changed during paging. Added barriers cover calendar,
resolver, storage/config rebinding and qualification mutation, alongside source
revision, rollout, malformed identity/pages, cancellation and missing coverage.

## Validation

- The unchanged `ownership_probe.py`, run against the complete baseline backend,
  fails because the previous canonical page remains reachable during the next
  read. It passes against the product. Both raw receipts are retained.
- Pure field expectations are independently reduced from the complete source
  through K130; tests cover 89/97/101/10007m and 1/7/256-row pages, gaps,
  duplicates, forming/bad bounds, nonfinite values, unknown enhancements,
  anchors/calendar boundaries, raw-page lifetime and atomic rejection of a
  misordered page followed by a corrected continuation.
- Actual default BackfillEngine + fresh SQLite tests cover source fetch,
  canonical read, native commits, target writer and final query. A late failed,
  stale or cancelled page produces no unproved target write, and reservations
  release. The public fork loopback transport contract remains in regression.
- Source verification includes interval/aggregation, backfill, query/cache,
  lifecycle/delivery/recovery, manual history, revision/GC, architecture and Pyne
  retirement contracts. Final counts and immutable provenance are in evidence.

`compare_core.py` runs unchanged against the complete baseline and product. Its
64 fixed/mixed cases exercise normal, gap, duplicate, unknown, wrong-grid/bounds,
nonfinite and forming-target inputs. Product batch results equal baseline
exactly. Paged outputs at 1/7/256 rows use the existing K130 equivalence contract
(rel 1e-12 / abs 1e-8); IEEE grouping is not asserted bitwise associative. Raw
results report absolute and relative differences, including high-dynamic-range
sums. No precision difference is hidden by a result hash alone.

## Final product results

Final product regression: **1,712 passed**, six existing warnings; final core /
page contracts: 94 passed. The earlier 1,706-test run preceded the cheap owner
check and final batch-index refinement. Both XML/log receipts are retained.

| Targets / variant | Canonical pages / source rows | Peak live canonical rows | Reconcile tracemalloc peak bytes | Reconcile CPU / wall ms |
| --- | ---: | ---: | ---: | ---: |
| 1 / baseline | 4 / 336 | 336 | 857,657 | 150.453 / 152.906 |
| 1 / product | 4 / 336 | 256 | 780,652 | 158.511 / 159.493 |
| 16 / baseline | 86 / 5,459 | 5,459 | 10,409,812 | 1055.029 / 1071.118 |
| 16 / product | 86 / 5,459 | 256 | 988,285 | 1033.054 / 1046.220 |

All source/target hashes, fetch-task counts, canonical reads, native/custom
writes and written ranges match in these cases. End-of-run reservations and
live canonical row counts are zero. Small-request overhead remains; these are
single instrumented-host samples, not stable end-to-end latency qualification.

## Cost methodology and retained attempts

`measure.py` runs one fresh process per variant/case with a default DataManager
budget and actual BackfillEngine/SQLite owners. The source upstream is synthetic,
not public network qualification. It requests 1 or 16 closed 20011m targets;
scan span is explicitly configured to that same complete demand in both variants.
No source/target work, metadata or field mask is reduced between variants.

A small row subclass counts live canonical dictionaries without retaining weakref
lists; its overhead is present in both variants. Reconcile CPU/wall/tracemalloc
include that instrumentation. Canonical SQL page counters describe this stage,
not every metadata/storage query. Whole interpreter peak RSS is recorded but is
not attributed to aggregation or treated as a resource-budget pass. Runs are
sequential; unrelated host work is uncontrolled.

The initial benchmark harness accessed a nonexistent DataManager private field
and omitted its synthetic fetcher's close hook; the failed log is preserved.
`measure-v2-*` and `profile-summary` retain the genuine excessive-qualification
CPU regression. Later measurements retain memory reduction without claiming
stable latency improvement. Fetch-result payloads remain in the returned report
in both variants; report/import/download streaming is still separate work.

The first new invalid-input test incorrectly compared grouped float sums with
exact dictionary equality; that failed log remains. Tests now apply the already
frozen K130 tolerance for numeric fields and exact coverage/closure/unknown/shape
checks. Production tolerance, source finality and field requirements were not
relaxed to obtain a pass.

```sh
CANDLE_DATA_DIR="$PWD/output/h127-data" PYTHONPATH=backend python docs/qa/mixed-canonical-streaming-127-20261112/run-regression.py
PYTHONPATH=/scratch/full-baseline/backend python -m pytest docs/qa/mixed-canonical-streaming-127-20261112/ownership_probe.py -q
PYTHONPATH=backend python -m pytest docs/qa/mixed-canonical-streaming-127-20261112/ownership_probe.py -q
PYTHONPATH=/scratch/full-baseline/backend python docs/qa/mixed-canonical-streaming-127-20261112/compare_core.py batch
PYTHONPATH=backend python docs/qa/mixed-canonical-streaming-127-20261112/compare_core.py 256
PYTHONPATH=backend python docs/qa/mixed-canonical-streaming-127-20261112/measure.py 20011 16
```

## Rollout / remaining original acceptance

The existing `BACKFILL_MIXED_CUSTOM_HISTORY=false` rollback restores original
mixed planning behavior while preserving committed source rows, revisions and
receipts. The page stream applies to the already-qualified mixed scope; it does
not admit calendar/replay/new providers, and native-authority requirements remain.

This delivers canonical reconciliation streaming, not end-to-end download/import
and report lifetime closure. Unqualified/custom batch paths, live mixed
prefix/tail composition, source/archive cost qualification, scheduling, full
resource accounting, real native/cold/continuous load and indicator/strategy
acceptance remain governed by the original #127/#126 requirements. Earlier
native receipts do not automatically qualify this changed backend revision.

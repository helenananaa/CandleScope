# R129 bounded shared source preparation / D126 ownership

Base: `85bc9412f19bdd5b0037607b3601ec651c6c0e09` (PR #372).
Product commits and SHA-256 source receipts are in `source-hashes.json`.
Refs #129 and #126. Both parent issues remain open.

## Delivered behavior

Default source dispatch can prepare one immutable component value for multiple
compatible derived targets. Each target retains its own admission, replacement,
coverage/finality decisions, incremental index and accumulator. This consumes the
existing K130 conversion/math and D126 memory owner; it adds no persistent source
cache, shared block manager, writer, delivery journal or source subscription.

Preparation lasts for one market frame/backfill dispatch and retains only its
latest input value. Qualification caches at most 128 target handles and refreshes
on target changes. Child tasks, direct ingest, replaced router callbacks, public
custom merge strategies, custom adapters, nested/oversized provenance and fewer
than two compatible component targets keep independent preparation. A flat source
reference must have at most 32 scalar entries and a conservative 2 KiB size.

The existing realtime-state owner admits reusable work allowances of 16 KiB,
at most 64 simultaneous slots. These are capacity estimates, not resident input
caches or claimed allocated bytes. Reuse avoids traversing all owners per tick;
detach, rollback and stop reclaim idle capacity. Failed optional admission keeps
the mandatory independent source/close route. Cancellation clears task-local
values and service references. No global budget or owner limit increases.

Before sharing, two real ownership defects were repaired: a component's nested
source_ref was mutable through a published copy, and the original input could
mutate accepted nested references. ReadonlyFields now recursively captures nested
containers; source_refs keeps a separate deep-copied JSON shape. Cycles and
unsupported opaque values fail before owner mutation. Built-in scalar values and
immutable NumPy numerics preserve precision; mutable scalar subclasses are
captured as base values. Published old versions remain stable after amendments.

Heap measurement also held temporary owner root containers too briefly. Python
could recycle a first owner's visited container ID into a later owner's graph,
under-counting or reporting zero for realtime-state. The diagnostic now keeps all
visited owner views alive until traversal ends. This changes measurement only;
it neither deletes data nor claims physical memory savings from accounting.

## Validation and provenance

- `nested-before.log.gz`: two pre-fix aliasing failures; 119/122 related tests
  subsequently passed (`nested-after` / `nested-final`).
- `tests-final.log.gz` / XML: **1,578 passed**, six existing warnings, on
  `ce9f6e5ea1afe8f171e85420599a2646a1e04fb6` before the last scalar and heap fixes.
- `shared-owned-scalars.log.gz`: **24 passed** after scalar capture refinement.
- `heap-roots-before.log.gz`: deterministic pre-fix temporary-view lifetime
  failure; `heap-roots-after.log.gz` / XML: **70 passed** on final product code,
  including 25 shared-input cases plus revision/cache metadata contracts.
- `source-journal.log.gz` / XML: 28 fork/source contracts passed.
- Architecture checks passed; new shared-input tests are in the cloud integration
  selector. Cloud run status is recorded in the PR, independently of local proof.

The controlled tests include full source event traces (forming, close, correction,
quality/status/finality/reason/ticks/watermarks and nine storage fields), default
DataManager with real temporary SQLite/journal/cache/query, pinned fork protocol
parsing through source journal and durable delivery, identities/unknown fields,
rollout, cancellation, budget deferral, extension hooks and slot reclamation.
No public network or native desktop acceptance is claimed by these tests.

`shared-final.log.gz` / XML preserves an earlier harness failure: epoch-zero source
frames ran against the real current clock and prematurely expired provisional
states. Finalization strategy had already captured its timeout before a later
configuration assignment. The corrected test controls the source clock instead
of changing product timing; `shared-final2` passed all then-current 21 cases.

Reproduce from repository root with the project's Python environment:

```sh
CANDLE_DATA_DIR="$PWD/output/r129-test-data" PYTHONPATH=backend python docs/qa/realtime-shared-input-129-20261112/run-regression.py
PYTHONPATH=backend python -m pytest backend/tests/test_shared_component_input.py backend/tests/test_kline_revision_contract.py backend/tests/test_cache_metadata_budget.py -q
python backend/scripts/check_architecture.py
```

## Same-input cost comparison

`measure.py` runs one fresh process per variant/case. Baseline is the complete
backend from the base SHA. Independent is final product with sharing disabled;
shared is final product with sharing enabled. Both new variants include the
ownership and diagnostic fixes. All nine v2 input hashes and final hashes match
within their cases (nine storage fields, status/finality, ticks and watermarks).

| Case / variant | Measured normalizations | Component references / unique values | Component graph bytes | Held-root heap bytes | CPU P50 / P95 / P99 μs |
| --- | ---: | ---: | ---: | ---: | ---: |
| single baseline | 512 | 33 / 33 | 30,862 | 302,164 | 119 / 123 / 143 |
| single independent | 512 | 33 / 33 | 30,862 | 302,220 | 139 / 146 / 172 |
| single shared | 512 | 33 / 33 | 30,862 | 302,220 | 148 / 155 / 183 |
| multi baseline | 2,048 | 260 / 260 | 223,470 | 571,249 | 354 / 370 / 401 |
| multi independent | 2,048 | 260 / 260 | 223,470 | 571,305 | 419 / 440 / 478 |
| multi shared | 512 | 260 / 65 | 61,086 | 408,921 | 388 / 415 / 461 |
| long baseline | 1,024 | 8,196 / 8,196 | 7,000,814 | 8,719,681 | 357 / 378 / 448 |
| long independent | 1,024 | 8,196 / 8,196 | 7,000,814 | 8,719,737 | 422 / 439 / 500 |
| long shared | 256 | 8,196 / 2,049 | 1,886,366 | 3,605,289 | 389 / 413 / 449 |

Single: native 1m + 89m, 32 warm minutes, 512 cumulative forming updates. Multi:
native 1m + 89/97/101/10007m, 64 warm minutes, 512 updates. Long: native 1m +
10007/10009/10037/10039m, 2,048 warm minutes, 256 updates. Each has 200 cached
series in the common registry. Preparation calls are instrumented in all variants.

These are isolated computation costs: created/updated previews disabled, closes
retained, no indicators/strategies/network/native UI. Host background work is not
controlled. Sharing saves repeated normalization and retained component values
versus the safe independent implementation; ownership validation and dispatch
qualification add cost, including a single-target regression and CPU costs above
the old shallow baseline. This is **not** a stable CPU, event-loop, whole-app RSS
or native performance pass. Raw wall percentiles, warm tracemalloc, process peak
RSS, configuration, module paths and hashes are retained in all JSON receipts.

Initial `measure-*.json.gz` results precede the root-lifetime diagnostic fix and
have unreliable registry heap totals. `measure-v2-*.json.gz` adds a separately
held-root traversal on every variant; final product registry totals agree with
it. Baseline registry totals remain unreliable and must not be compared directly.
`measure-summary.json` uses the held-root totals. No failed run is discarded.

```sh
# Export complete baseline backend from the recorded SHA into a scratch folder.
PYTHONPATH=/scratch/baseline/backend python docs/qa/realtime-shared-input-129-20261112/measure.py baseline long
PYTHONPATH=backend python docs/qa/realtime-shared-input-129-20261112/measure.py independent long
PYTHONPATH=backend python docs/qa/realtime-shared-input-129-20261112/measure.py shared long
```

## Rollout and remaining qualification

`BAR_AGG_SHARED_COMPONENT_INPUTS=false` restores independent preparation without
undoing immutable publication, revisions or accepted source data. Toggle tests
preserve the full event trace. Existing native save/exit/restart evidence from
earlier PRs does not qualify this product revision.

This is per-dispatch sharing, not global deduplication of every retained historical
version. Interrupted fan-out/retry can leave equivalent old values in independent
targets. Per-target indexes, correction state, closed retention, idle pipelines,
pending durable payloads and history buffers still need their own resource and
lifecycle acceptance. Plain-target detach/re-add across awaited callbacks also
needs additional generation tests. H127 mixed backfill remains bounded work with
separate streaming/full-source qualification. Original #126/#129 matrices, real
native multi-chart/continuous operation, event-loop costs, indicators/strategies
and release acceptance remain outstanding.

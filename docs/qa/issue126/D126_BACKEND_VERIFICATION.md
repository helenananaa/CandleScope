# Issue #126 backend stage verification

Baseline: `b84b5e3` main, with native query fencing in `40f789bf`.
Candidate: D126 implementation in this PR. All commands used the worktree's
Python 3.12.15 virtual environment and an isolated `CANDLE_DATA_DIR`; no user's
market database was used. Desktop/browser acceptance was explicitly excluded.

## Delivered and verified

- Immutable BarData, detached query/event/aggregator snapshots, immutable shared
  component fields, and the indicator consumer migration.
- SQLite transaction revisions, coalesced changes, cache adoption and observable
  polling, min_revision, real SQLite read/repair races, queued work fencing,
  deletion/empty-deletion protection and atomic replacement.
- Existing real-time journal remains the writer. Tests exercise deletion before
  receipt recovery in a separate Python process, separate-process raw SQL
  amendments, publication failure, ordered receipts, new legitimate work after
  deletion, old builder rejection and old recovery-watch cleanup.
- Derived receipts check source revisions even when no target row existed.
  Own query materialization commits are accepted. Retention does not cascade
  into independently protected materialized history.
- Job deletion floors persist across restart and migration; canonical backfill
  adoption cannot resurrect deleted rows from an old notification.
- Shared budget registration/leases, deep-query deferral, history-work admission,
  active-state protection, safe GC pressure, deduplicated diagnostic roots,
  in-flight delivery accounting and release on cancellation.
- Writer inventory and migration/rollback boundaries are in the
  [D126 contract](../../architecture/KLINE_REVISION_CONTRACT.md).

The targeted regression command covers query/cache, aggregator contracts,
backfill, archive imports, manual history/API, durable delivery, custom intervals,
retention/GC, maintenance and indicator consumers. The latest result is recorded
in `verification.json`. Five warnings are existing FastAPI on_event deprecations.
Architecture and whitespace checks also pass. The suite is not the entire
repository's test suite, and is not desktop user-flow evidence.

## Reproduce

From the repository root, choose a dedicated scratch directory:

```sh
export CANDLE_DATA_DIR="$PWD/output/issue126-query-fencing/data"
export PYTHONPATH=backend
.venv/bin/python -m pytest -q --tb=short \
  backend/tests/test_bar_cache*.py backend/tests/test_query*.py \
  backend/tests/test_data_engine_phase1_boundaries.py backend/tests/test_kline*.py \
  backend/tests/test_data_manager_gc.py backend/tests/test_gc_execution_safety.py \
  backend/tests/test_maintenance_facade.py backend/tests/test_bar_delivery*.py \
  backend/tests/test_custom_interval*.py backend/tests/test_manual_history*.py \
  backend/tests/test_storage_retention_gc.py backend/tests/test_backfill*.py \
  backend/tests/test_history_archive*.py backend/tests/test_bar_aggregator_contracts.py \
  backend/tests/test_interval_routing_phase3.py backend/tests/test_event_bus*.py \
  backend/tests/test_data_manager_warm_start_bridge.py backend/tests/test_indicator*.py
.venv/bin/python -B backend/scripts/check_architecture.py
git diff --check
.venv/bin/python backend/scripts/benchmark_kline_consistency.py candidate
```

For comparison, extract `git archive 40f789bf backend` into a separate scratch
folder and point PYTHONPATH at that complete backend, keeping the same interpreter
and benchmark script; use the `baseline` argument. Do not import only an older
cache.py alongside new models. Each benchmark process creates its own temporary
SQLite file and removes it after the run.

## Measurements and limits

[All four runs](measurements.json) include P50/P95/P99, sample counts, retained
Python allocations and process peak RSS. Run order was baseline, candidate,
candidate, baseline. Host contention varied, and the first baseline ran alongside
a static architecture check. The reverse-order repeat pair below avoids that
self-created overlap. No frozen end-to-end performance budget was available, so
these are measured costs, not a release performance pass.

| Scenario | Before P50 / P95 / P99 (ms) | After P50 / P95 / P99 (ms) |
| --- | --- | --- |
| construct_record | 0.0008 / 0.0009 / 0.0011 | 0.0022 / 0.0056 / 0.0127 |
| tail_upsert | 0.0015 / 0.0016 / 0.0016 | 0.0016 / 0.0036 / 0.0196 |
| event_snapshot | 0.0254 / 0.0274 / 0.0501 | 0.0163 / 0.0455 / 0.1086 |
| warm_1 | 0.5006 / 0.5464 / 0.7785 | 0.5252 / 0.7957 / 2.0173 |
| warm_1500 | 0.7371 / 0.8630 / 1.1316 | 0.8392 / 1.4453 / 1.8365 |
| warm_5000 | 1.3106 / 1.8653 / 3.1707 | 1.3073 / 1.8493 / 3.1658 |
| cold_sqlite_1500 | 9.7489 / 12.2428 / 15.3600 | 15.1854 / 19.0939 / 19.9103 |
| write_1 | 0.4059 / 0.6861 / 1.7297 | 1.3037 / 1.5295 / 4.2437 |
| write_1000 | 8.0007 / 8.8709 / 8.8709 | 16.4809 / 18.4853 / 18.4853 |
| publisher_0 | 0.0035 / 0.0045 / 0.0321 | 0.0169 / 0.0179 / 0.0639 |
| publisher_1000 | 0.0035 / 0.0037 / 0.0158 | 0.1303 / 0.1551 / 0.1889 |
The controlled cohort is 5,000 BarData/cache records plus 500 copied event
snapshots. Traced retained allocations were 1,976,520 → 1,872,392 bytes (5.27%
less); traced peaks were 1,984,032 → 1,878,912 bytes. Event snapshots safely shared
0/500 → 500/500 immutable records. This is not the entire runtime memory model.
Whole-interpreter peak RSS in the repeat pair was 212,828,160 → 224,067,584 bytes;
there is **no demonstrated total RSS reduction**.

Warm-query medians were similar in these samples, with variable tails. Cold reads
and writes are more expensive because they validate/record durable revisions.
Publishing 1,000-component state costs about 0.13 ms median versus 0.0035 ms for
the old unsafe shared-reference publication. The new path copies one component
index, not all historical states; immutable component values are shared. These
costs remain visible for downstream performance acceptance rather than being
hidden by the smaller event-record allocation figure.

All four runs have identical input hashes, immutable query-row hashes for
1/1,500/5,000 bars, and canonical SQLite hashes after the same 80 write iterations.
The behavioral suite separately checks enhanced fields, finality, correction,
quality arbitration, coverage, event delivery and indicator inputs; the hash
microbenchmark alone does not prove those whole-flow properties.

## Remaining acceptance outside this stage

- Desktop/browser real-time, deep history, correction, indicators, close/reopen
  and native/network latency were not executed, as requested.
- #130/#127/#129 must provide their minimum block/history/realtime consumer
  integration receipts and joint resource/initialization acceptance. This PR
  supplies the interface and current producer wiring; it does not implement
  their separate executors, dependency graph or state-window reconstruction.
- Native long-duration multi-chart RSS, event-loop latency, viewport first paint,
  source replay and full rollback-binary qualification are not inferred from
  these component tests. The operational rollback procedure preserves revision
  metadata and requires revision-aware writers.
- Legacy derived rows with ambiguous native provenance cannot be inferred safely;
  the migration registers known provenance. Change rows/tombstones are coalesced
  per historical identity, not globally size-capped across unlimited new identities.

Keep #126 open for these acceptance boundaries; this PR releases 126-A/D126 and
the 126-C common interface plus current BarCache/GC wiring. It does not claim the
entire four-issue joint milestone is finished.

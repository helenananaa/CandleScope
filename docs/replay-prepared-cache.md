# Replay preparation cache

See [the subsequent first-preparation work](replay-first-preparation-work.md)
for newer measurements and cache format v3. This document records the initial
persistent-cache implementation.

This continues the prepared interval jump in `cd0d5ee6`. It reduces the work
before replay controls become ready; the exact event-directed jump remains the
same. Execution ordering, financial results and event stopping are unchanged.

## Changes

- Save the prepared market window beside the replay database in
  `<database>.prepared/<session-key>.zlib`. Each session replaces its previous
  window atomically. This is a disposable derived cache, not a recovery log.
- Store scalar JSON with zlib corruption detection. Deduplicate retained
  display bars across builder checkpoints. No Python object deserialization.
- Bind the format version to the frozen source reference, builder configuration,
  replay start and halt schedule. On load, compare the current source chain and
  exact builder state at the restored cursor. A cache can be reused after
  progress within its window, not just at the original preparation point.
- Invalid, obsolete, mismatched or unavailable caches fall back to preparation.
  Cache-write failures do not fail replay. No database schema change is required.
- Account summaries retain their existing position/ledger/configuration key.
  A changed account reuses market preparation but recalculates its valuation.
- Use the existing projection-free builder path during first preparation, and
  reuse bounded immutable interval parse results (512 entries).
- Renew a consumed nonterminal window; it no longer remains falsely compatible
  at its end and forces subsequent advancement onto the slower fallback.

The cache version must change if persisted builder or source-chain semantics
change. Cache files may be deleted without losing training history. Their
absence requires another preparation. Old database backups need not include
these files.

## Measurements on 2026-09-10

Actual existing local run, 100,000 future BAR events:

| Preparation | Observed time |
| --- | ---: |
| Previous implementation, earlier measurement | 32.286 s |
| First preparation with this implementation | 15.861 s |
| New backend process, load persisted cache | 3.782 s |
| Repeat preparation in the same process | 0.028 s |

These are individual endpoint measurements, not chart-paint times or percentile
guarantees. Before/after cursor, revision and state hashes matched on every
call. The user's training progress was not advanced. The previous 32-second
sample was not rerun in the same process.

A separate same-process synthetic 100,000-event comparison measured the
committed implementation at 14.569 s, new first preparation including cache
write at 10.988 s, and cache loading at 2.289 s. The real run's cache occupies
16,075,376 bytes. Machine activity and dataset contents affect these timings.

Evidence: `output/replay-latency-sampling-20260909/cold-cache-benchmark.json`,
`cold-cache-live-first.json`, `cold-cache-live-reload.json` and
`cold-cache-live-warm.json`.

## Verification and remaining cost

- 93 focused regression cases passed: prepared cache, indexed advancement,
  recorded interval, interval advancement, bar builder and interval policy.
- One additional integration case passed for advancing across multiple small
  preparation windows and comparing financial/review/recovery results.
- Coverage includes changed positions, advanced-cursor restart, source/config/
  chain mismatch, corrupt/obsolete cache, unavailable disk, order/funding/risk
  boundaries, rollback and checkpoint recovery. Ruff and diff checks passed.
- A preliminary new test used an internally inconsistent position fixture and
  failed; the corrected test and final regression pass. It was a fixture error,
  not a relaxed financial assertion.

First preparation is still linear. Reloading avoids source scanning, per-bar
validation and hash-chain construction, but JSON decoding and rebuilding range
trees are also linear. Account changes can still require linear valuation work.
This does not establish instant cold opening or constant-time preparation.

The normal backend was restarted with the same configuration and existing
database; it now listens on port 18080 (observed PID 38924), with the user's
index ready. Backups before the two restarts are under
`output/replay-latency-20260909/before-interval-replay-42056.db` and
`before-interval-replay-32972.db`, with their dataset directories.

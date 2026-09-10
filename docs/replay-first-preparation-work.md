# First preparation: reduced repeated work, remaining latency

The subsequent [shared market index](replay-shared-market-index.md) addresses
the architectural issue described here. This document retains the earlier
measurements and limits of session-specific preparation.

This follows [the persistent preparation cache](replay-prepared-cache.md).
It reduces computational work, but does **not** qualify first opening as fast.
Preparation still scans up to 100,000 future base bars.

## Implementation

- During preparation, retain a bounded mapping of already calculated closed-bar
  chain prefixes. Evicting a retained candle reuses its original prefix hash
  instead of hashing it again. Restored initial windows use the original path
  until covered. Derived hashes are excluded from snapshots and frozen copies.
- Source-event hashing uses the existing canonical encoder, including its
  optional native implementation and original fallback. Hash bytes are unchanged.
- A repository-validated immutable ReplayBar carries a transient numeric
  validation receipt outside its dataclass/wire/hash fields. Builder time,
  ordering, alignment and synthetic-policy checks remain. Dataclasses.replace
  drops the receipt; explicitly shifting only time preserves it. Zero shift
  returns the same immutable object.
- Already canonical decimal spellings avoid redundant Decimal formatting.
  Repository float conversion preserves the previous decimal interpretation,
  including exponent expansion, without repeated parse/format cycles. Original
  noncanonical, Unicode-digit and invalid-value handling remains tested.
- Cache checkpoints store slices into a chronological pool of closed bars,
  rather than repeatedly enumerating the full retained window. Scalar encoding
  uses compiled attribute getters and optional native JSON encoding.
- Cache version v3 has an uncompressed version header. Obsolete files are
  rejected before expensive decompression/JSON decoding; corruption, mismatches
  and write failures still fall back without losing training history.

## Evidence (2026-09-10)

All artifacts are under `output/replay-latency-sampling-20260909`.

| Measurement | Observed duration |
| --- | ---: |
| Previous preparation implementation, same 100,000 real rows, already ingested | 13.891 s |
| Updated preparation, same rows, including cache write | 6.602 s |
| Full preparation on an isolated copy of the actual run, no existing cache | 12.277 s |
| Normal service, final cold cache-miss check, no profiler | 15.118 s |

The earlier normal-service measurement was 15.861 s. Intermediate normal-service
runs measured 18.222 s and 24.342 s; they remain in the evidence. Therefore the
end-to-end improvement is small and variable, despite the substantial reduction
in repeated computation. Do not report a twofold first-opening speedup.

The same-data comparison retained both source chain and terminal builder hashes:
`first-preparation-previous-exact.json` and `first-preparation-final-exact.json`.
Its row acquisition was outside the timer, so it is not an opening benchmark.
`real-first-final/timings.json` includes real frozen-source paging and validation
in an isolated replay service. The first diagnostic copy lacked associated
HEDGE input files and failed after producing the market profile; the completed
run copied the associated archives and its result is separate.

Live results are `cold-cache-live-first-optimized.json`,
`cold-cache-live-first-final.json`, and `cold-cache-live-first-clean.json`.
Every live check compared cursor, revision and state hashes before/after. The
user's replay progress was not advanced. The final check backed up and removed
only the disposable index before requesting preparation.

The temporary live profiler recorded 30.920 s inside preparation and 31.095 s
for the operation overall: queueing, curve registration and input lookup were
minor. These profiled durations include instrumentation overhead and are not
latency benchmarks. They locate remaining work in market preparation, including
frozen-source reads and first-pass validation, rather than a large queue delay.

## Validation and runtime

- 171 regression cases passed across replay indexing/intervals, dataset, blind
  time, halts, canonical hashing, broker determinism, BAR and tape execution.
- After the final ingestion changes, 65 relevant cases passed.
- After the final cache-format changes, 27 cache/preparation cases passed,
  including hourly/daily partial buckets with native JSON present or absent.
- Tests include 2,000 decimal spellings and 2,000 float-conversion comparisons,
  invalid inputs, unchanged historical JSON hash bytes, bounded prefix-hash
  reuse, cache recovery, financial comparisons and exact event stopping.
- Ruff and diff checks passed. Raw logs and XML are retained.

The normal backend has been restored on port 18080 (observed PID 4600), with
100,000 events prepared for the existing run. Temporary instrumentation is not
loaded. No frontend or database-schema change was needed in this round.
The prior and current preparation improvements remain uncommitted.

First opening still has material latency. A further design must reduce or
relocate first-use preparation of the entire future window, while measuring
both readiness and the subsequent first large step. Reducing only the initial
window and hiding a later stall would not resolve the interaction problem.

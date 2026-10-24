# Replay indicator input ranges — 2026-10-24

The current baseline is `df7bda68` (PR #86), including `viewport-v1`.
The older 34–36 second full-origin RSI observation predates that policy and
must not be treated as a measurement of the current implementation.

## Confirmed failure and ownership mismatch

Prepared replay EMA(200) requests 1000 warmup bars. The history adapter returned
up to 999 bars at once, violating the viewport engine's 500-bar input contract
and failing with `indicator reader changed its display cursor`.

Small indicator ranges also inherited a chart page's maximum row limit. A
42-bar RSI prefix consequently projected 1000 one-minute bars, or 91 ninety-minute
bars (8190 base rows), then discarded most of them. This work occurs before the
ordinary indicator math, so changing formulas, adding worker lanes or tuning GC
would not correct the underlying range/page mismatch.

The adapter now propagates the actual requested bucket count, retaining one
predecessor for gap evidence. It limits each chunk to the existing 500-bar
viewport calculation contract. Canonical/tape consumers keep their existing page
capacity. All paths retain calendar stepping, native authority seams,
source revision checks, revealed bounds, cancellation and resumable anchors.
No account, execution, checkpoint format or indicator formula changes.

## Controlled service comparison

Three alternating baseline/candidate runs, each in a fresh isolated preparation
store, use the production preparation/history/indicator services with a
deterministic provider. Four offset windows each request MA and RSI with distinct
periods, avoiding schedule-dependent shared-anchor reuse. Every cold batch
consumes exactly 268 mathematical warmup bars and renders 160 points per line set.

| Four-window batch | Baseline median | Candidate median | Projected display bars |
| --- | ---: | ---: | ---: |
| Cold 1m | 458 ms | 79 ms | 8000 → 276 |
| Cold 90m | 1814 ms | 727 ms | 728 → 276 |
| Warm 1m | 21 ms | 21 ms | 0 → 0 |
| Warm 90m | 17 ms | 18 ms | 0 → 0 |

These are service measurements, not native first-paint latency, production
network timing or P95. Source preparation is included; provider network latency
is not. Raw scripts, fixed-work comparisons and regression receipts are in the
local `output/replay-shared-history-20261024/` evidence directory.

Eight new integration cases cover EMA(200), RSI(14), 1m/7m/90m, prepared/progressive
sources and blind time mapping. They verify full numerical outputs against the
ordinary builtin, exact warmup consumption and bounded source projection work.
The initial red run reproduced both the EMA failure and excess projection.

## Further structural work and acceptance boundary

Warm repeated reads already use durable mathematical anchors and perform no
history projection in this comparison. A new shared projection cache is not
justified by that path. If native multi-chart measurements still show repeated
closed-source projection across independently cold ranges, the next architectural
candidate is a bounded input/projection owner keyed by immutable source objects
and source grids, shared across runs. It must keep all account state out, handle
cache release/generation changes and drain cancellation before publishing data.

Whole-app cold/warm P95, long multi-chart resource use, first materialization over
real network conditions and the other original 157 acceptance items remain
separate. Windows stays independent. Native package/restart results must be bound
to the merged revision and recorded separately from the service comparison.

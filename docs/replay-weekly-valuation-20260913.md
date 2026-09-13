# Weekly portfolio valuation optimization — 2026-09-13

The weekly BAR/HEDGE candidate now values a requested portfolio interval with
bounded integer array operations. It retains the existing lowpoint/endpoint
phases, review records, durable writes and financial results. Enablement remains
OFF; this is local optimization evidence, not release qualification.

## Implementation

`backend/app/replay/training/portfolio_prices.py` prepares readonly, market-only
price deltas and equal-time cohort boundaries alongside its existing index.
The query binds each track's first delta to the supplied current mark, applies
current position weights, and observes equity only after an entire cohort.
It preserves the first occurrence of a strict minimum and exact drawdown.

Before NumPy int64 arithmetic, arbitrary-size Python integers bound the initial
equity, every partial cohort, cumulative delta and drawdown. Unsafe magnitudes
use the previous arbitrary-integer scanner; exotic precision retains the
existing 60-digit Decimal reference path. Short ranges also use the scanner.
NumPy is already a pinned backend dependency. No floating-point valuation is
introduced.

No future account states are cached. Valuation is still linear in requested
market events, with native array execution replacing the Python event loop.
Additional persistent arrays occupy roughly 32 bytes per event plus 8 bytes per
cohort, excluding small array headers. Preparation is paid once per market index.

## Service comparison

Retained real Binance 1m seed, eight held CROSS/LONG products, three weekly
advances over the same 21-day archive. Independent cloned databases, normal
timing without cProfile:

| Weekly operation | Before command ms | After command ms | Before summary ms | After summary ms |
|---|---:|---:|---:|---:|
| 1 | 196.08 | 104.04 | 26.59 | 1.10 |
| 2 | 81.82 | 43.14 | 25.12 | 1.08 |
| 3 / archive tail | 265.73 | 170.66 | 19.85 | 0.83 |

These are three paired diagnostics, not percentile qualification. Host and
storage variation also affect the total command time. Preparation measured
32.60 s before and 23.78 s after; this single pair does not establish a preparation
speedup. The first two commands use one transaction and zero source-event
reducer calls. The archive-tail command still uses 11 transactions and eight
individual reducer calls in both versions. The eight terminal events are not
the skipped weekly history; this change does not optimize terminal persistence.

Evidence: `output/replay-weekly-20260913/{before,after}.json` and `probe.py`.
`source-before/portfolio_prices.py` retains the immediately preceding code.

## Correctness and recovery

- 63 relevant tests pass: batch/scalar equivalence, global cohorts, unequal
  grids, duplicate minima, supplied initial marks, int64 fallback, exotic
  precision, multi-phase rollback, financial projections, exports and recovery.
- Both real-service account audits PASS. All eight track-head objects match.
- Seven financial/interval tables match, excluding wall-clock `updated_at_ms`
  fields on positions and margin buckets. Interval summary and basis bytes match.
- Ruff and scoped diff whitespace checks pass.
- After the final browser cycle, the server was stopped and its actual database
  reopened without resetting the seed. All eight actors recovered at source
  sequence 30240; account audit PASS, 120 revealed history bars loaded, and seven
  financial-table hashes stayed unchanged across recovery. Recovery took 8.03 s
  and the explicit account audit 16.63 s. See `real-recovery.json` and its helper.

Evidence: `output/replay-weekly-20260913/tests.xml` and
`financial-comparison.json`.

## Browser diagnostics

Three independent resets, three weekly clicks each, nine successful operations.
Real Windows Chrome, visible and focused, 1280×720 at DPR 1.5, eight held products,
account/capability rails, MACD and VOL. Each cycle preloaded 54 weekly candles
and nonempty indicator history. Tests were finished before sampling.

| Cycle | First main update ms | Middle main update ms | Archive-tail main update ms |
|---|---:|---:|---:|
| 1 | 208.7 | 98.5 | 248.6 |
| 2 | 199.8 | 111.8 | 282.4 |
| 3 | 146.9 | 80.5 | 211.4 |

All nine responses are HTTP 200 with eight FULL tracks. Largest indicator update
is 308.8 ms; first/subsequent animation-frame opportunities reach 297.8/313.2 ms.
These frame callbacks do not measure physical pixel presentation. Previous
three-click diagnostics were 238.1/113.4/322.3 ms; they are a prior run, not a
controlled browser A/B distribution.

The portfolio calculation is substantially faster, but the archive-tail operation
still exceeds the 200 ms main-update target. Its ordinary terminal settlement and
durable writes remain a follow-up hotspot. Nine clicks over a repeated 21-day
window do not satisfy the 100-operation weekly qualification requirement. No
production flags were enabled. Subsequent local commit packaging is recorded in
[the candidate commit note](replay-optimization-commit-20260913.md).

Evidence: `output/playwright/replay-weekly-20260913/weekly-{1,2,3}.json`,
`weekly-combined.json`, the preparation receipts, and
`output/replay-weekly-20260913/browser-summary.json`. An initial connection-refused
attempt while the test server was restarting is retained in `prepare-final-1.json`;
it is a setup failure and produced no measured click.

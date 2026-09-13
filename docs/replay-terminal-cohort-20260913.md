# Replay final BAR cohort optimization — 2026-09-13

The remaining same-time BAR steps at the end of a multi-track advance now
share one actor/risk/global-checkpoint transaction. They still execute the
ordinary STEP reducer once per market. This does not skip financial work,
extend public-input coverage or change SQLite durability.

## Scope and invariants

`training/terminal_cohort.py` is called by the production global coordinator
only for 2–8 BAR/HEDGE tracks with the multi-interval switch enabled, no required
book or exact historical-account dependency, no new account/input phase, and
exactly one planned BAR per track at the requested target. Previously settled
phase-30 marks are included in the same global checkpoint. Other input phases,
unequal next timestamps and incomplete cohorts keep the ordinary path.

The source plan already exists; this lane does not prepare or rebase eight
indexes again. Every actor builds an ordinary STEP candidate. SQL checks the
expected revisions/source sequences before writing and the actual final source
sequences/times after writing. The existing group coordinator holds actor
publication until commit and drains cancellation. The normal HEDGE risk check
and liquidation continuation remain in place.

The command boundary is not necessarily the end of the archive or index:
rebasing can extend the market window past the last candle requested by the
user. This distinction is covered by the new financial-equivalence tests.

An existing multi-interval recovery intent is advanced after a risk-safe cohort to the committed final
actors in the same transaction. A process exit between this commit and the
external result can resume from that boundary instead of rejecting a stale
interval bookmark.

## Validation

- CROSS and ISOLATED eight-market results match individual STEP persistence,
  including when the prepared index extends past the requested target.
- Injected checkpoint failure and an incorrect target time restore all actors
  and SQL projections, with no candidate events published.
- A subprocess exits immediately after the terminal group commits. Reopening
  the database and retrying the stored command reaches the correct final cursor
  and passes account audit.
- Initial related regression: 51 passed. Subsequent service/terminal run:
  34 passed. Final targeted tests including the process-exit case: 8 passed,
  28 deselected. These runs overlap and must not be added together.
- Ruff on the new module/tests, Python compilation and scoped whitespace checks
  pass. Existing unrelated workspace edits are preserved.

Evidence is retained in `output/replay-terminal-20260913/`, including test XML,
the immediately preceding service source, probe scripts and intermediate
diagnostics. Intermediate probes that still used 11 transactions are retained
as unsuccessful candidates. Timing collected during concurrent regression work
is diagnostic only.

## Final browser diagnostics

The same held-product workload is used: eight LONG/CROSS markets, Windows
Chrome visible/focused, 1280×720/DPR 1.5, 54 preloaded weekly candles, MACD,
volume and account/capability rails. Each cycle resets the same 21-day seed.
No regression test runs during these measured clicks.

| Cycle | First main update ms | Middle main update ms | Final main update ms |
|---|---:|---:|---:|
| 1 | 263.8 | 129.0 | 319.4 |
| 2 | 291.9 | 140.4 | 328.7 |
| 3 | 195.3 | 106.2 | 297.9 |

All nine commands succeed with eight FULL tracks. The largest indicator update
is 363.5 ms; first/subsequent animation-frame opportunities reach 349.6/372.0 ms.
Physical presentation was not measured. The 200 ms main-update target still
fails, and nine repeated-window operations do not qualify the required weekly
100-operation workload. Fewer commits alone do not establish an end-to-end win.

The actual final browser database was reopened without resetting the seed.
All eight actors restored at sequence 30240; account audit PASS, 120 revealed
history bars loaded, and seven financial-table hashes remained unchanged.
Recovery took 11.43 s; the explicit audit took 28.05 s (startup occurred alongside
baseline-server setup, so these are diagnostic timings).

Evidence: `output/playwright/replay-terminal-20260913/weekly-{1,2,3}.json`,
`weekly-combined.json`, preparation receipts, `browser-summary.json`, and
`real-recovery.json` under `output/replay-terminal-20260913/`.

## Baseline comparison and service counters

A fresh browser baseline uses the retained pre-change service module with the
same current dependencies, frontend, seed, indicators and viewport. Its three
main updates measure **206.3 / 106.1 / 238.9 ms**, with final indicator update
255.2 ms. It was measured after the three candidate cycles. The candidate did
not demonstrate a browser latency improvement in these samples; the final
candidate clicks were slower. This is insufficient to distinguish host/run
variation from a latency regression, and must not be promoted as a UI speedup.

Final unprofiled service run on the measured source:

| Operation | Before ms | Final candidate ms | Before transactions | Final transactions |
|---|---:|---:|---:|---:|
| First week | 140.10 | 118.21 | 1 | 1 |
| Middle week | 64.20 | 47.46 | 1 | 1 |
| Final week | 241.27 | 171.51 | 11 | 3 |

The final operation retains all eight real source-event reducer calls. Its
measured aggregate SQL commit time falls from 20.72 to 7.11 ms and writer work
from 127.84 to 86.85 ms. These are separate three-operation runs, not a repeated
paired distribution: even the untouched first/middle operations vary, so the
whole wall-time difference cannot be attributed to the patch. One-time
preparation is 33.34 s before and 28.48 s after, also not a preparation-speedup
claim. Evidence: `before.json`, `after-verified.json`, and
`output/playwright/replay-terminal-20260913/weekly-baseline.json`.

Multi-interval enablement remains OFF. Subsequent local commit packaging is
recorded in [the candidate commit note](replay-optimization-commit-20260913.md).
The useful verified outcomes are fewer durable commits, retained
financial semantics, atomic publication and recovery across the final-commit
window. Stable weekly browser performance remains unqualified.

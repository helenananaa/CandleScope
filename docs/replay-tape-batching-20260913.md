# AGG_TRADE bounded transaction batching — 2026-09-13

This change implements the first two stages of the approved tape optimization: durable command idempotency with a bounded actor cache, and exact global cohort transaction batching. It does not implement trade-range indexes or native reducers.

## Implementation

- Persistent actors consult the durable command table on an in-memory miss, including inside the serialized actor queue. Eviction preserves original successes, failures, and conflicting-envelope rejection after restart. Actors without durable persistence still reject capacity exhaustion.
- With `REPLAY_FAST_FORWARD_OPTIMIZATION_ENABLED=1`, 2–8 eligible ONE_WAY AGG_TRADE tracks share one SQLite transaction for up to 16 complete globally ordered timestamp cohorts. Planning reads at most 128 events per track and excludes an incomplete/terminal last timestamp.
- Every cohort still executes trade reducers, account/risk projections, source/event-chain checkpoints, global ordering, and review points. The optimization removes repeated transaction commits and public snapshots; it does not replace trade paths with candle endpoints.
- Resting orders, funding, historical accounts, books, HEDGE mode, divergent clocks and incomplete source cohorts use the existing coordinator. A liquidation interaction rolls back the entire unpublished batch and retries the original path.
- Each actor publishes one terminal snapshot only after the shared commit. Public sequences stay contiguous; source sequences remain exact. Cancellation drains an in-flight commit. A durable parent intent and full-track bookmarks support resuming after restart, including intervening scalar cohorts. Recovery uses the original `stop_on_event` default.

## Evidence

Real archived BTCUSDT + ETHUSDT perpetual aggTrades, 2026-07-30 UTC, the same saved seed with two long positions (BTC 0.001 / ETH 0.01), 10,000 USDT, CROSS / APPROX_PROXY, funding and books OFF. One `ADVANCE DISPLAY_BAR` command advances from 00:00:01 to 00:00:59.999.

| Case | Backend advance | SQLite transactions | Consumed trades |
|---|---:|---:|---:|
| Original fast flag ON | 29.249 s | 3,603 | 1,486 |
| Initial candidate exact cohort batching | 3.933 s | 73 | 1,486 |
| Final code repeat | 4.140 s | 73 | 1,486 |

The final repeat is 7.07x faster than the original in these single observations and uses 97.97% fewer transactions. Final per-track cursors and portfolio financial values/positions match the original. Derived revision counts, wall timestamps and the combined hedge relational state hash differ; legacy whole-state byte/hash equality is not claimed.

Raw evidence: `output/replay-tape-benchmark-20260913/held2-on-1m/result.json` and `opt-v1-held2-on-1m/result.json`; replay harness: `probe.py` in the same directory. These are isolated disposable service/database runs, not HTTP, chart update, frame or paint measurements. Single observations are not percentile estimates, and long-range speedups must not be extrapolated from this minute.

## Boundaries

The optimization retains the existing explicit flag and does not change the running service or production settings. Single-track tape still uses the existing execution path (with the durable-cache capacity fix). Long horizons still incur exact reducer/checkpoint/history costs. A progressing, cancelable tape job with a durable parent renews bounded coordinator windows; jobs without that recovery authority retain the original wave cap, and stalled windows cannot renew. Pending tape intents must be completed or recovered before rolling back to a binary that does not understand `tape-cohort-advance.v1` recovery.


## Long-run findings and regression checks

The initial candidate hour run hit the pre-existing 10,000-wave coordinator ceiling after roughly 55 minutes of market time. Its database had more than 40,000 durable commands on one actor, demonstrating that the former 4,096-command failure was bypassed without discarding durable idempotency. The original failed receipt is retained as `opt-v1-held2-on-1h/result.json`.

A second change renews bounded windows only when a durable tape job makes forward progress. Unit and real-service tests cover window renewal and unchanged standalone/BAR bounds. This does not reduce the remaining hour-long scan CPU cost.

Regression: 96 tests passed in 41.98 s across `test_replay_tape_phases.py`, `test_replay_multi_phase.py`, `test_replay_multitrack_batch.py`, `test_replay_service.py`, `test_replay_commands.py`, `test_replay_v2_training_phase5.py`, and `test_replay_v2_training_phase6.py`. This is a focused regression set, not the entire repository suite. A pre-existing heartbeat test double was updated to forward the existing private renewal argument.

Tests cover durable success/failure/conflict replay, eviction and restart, complete batch rollback on write failure, no publication before commit, contiguous terminal snapshots, cancellation draining and recovery, resting-order fallback, and an actual liquidation-inducing price excursion followed by price recovery. The excursion rolls back the speculative batch and is observed by the original coordinator.

Recovery qualification is limited to complete persisted global cohorts. The old wave-limit failure occurred inside an unfinished same-timestamp fallback cohort; its stale bookmark was correctly rejected with `ADVANCE_INTENT_CURSOR_CONFLICT` in the copied recovery trial. This negative result is not a successful recovery receipt. Do not relax fingerprints to resume partially committed fallback state. The final coordinator window change is checked with a fresh complete-hour run.


## Final receipts

- Final minute repeat: 4.1398593 s, 73 transactions, all 1,486 expected trades. `opt-final-minute-equivalence.json` compares the entire portfolio recursively, excluding only derived component revisions, wall timestamps and `/hedge_state/state_hash`; the remaining data and every cursor match the reference. Source hashes for that repeat are in `opt-final-source-hashes.json`.
- Fresh complete-hour scan with renewed windows: 504.4038871 s (8 min 24 s), 12,943 transactions, BTC 41,386 + ETH 41,759 consumed trades, both clocks exactly at 00:59:59.999. Durable command counts reached 43,832 and 39,246. See `opt-v3-hour-counts.json` and `opt-v3-held2-on-1h/result.json`. The reopened service account audit passed (`account-audit.json`). This is still slow and is not a before/after hour speed ratio: the original hour measurements were censored at 90 seconds.
- The hour run overlapped an 8.56-second, 11-test regression run. It loaded the window-renewal implementation before the final clock-only bookmark addition; that addition passed the terminal-reply recovery test and the final minute repeat. Do not label this an uncontended, immutable-final-source hour performance qualification.
- Final tape regression: 11 passed in 8.56 s after the terminal-bookmark addition; selected-file Ruff and whitespace checks passed. The earlier broader regression had 96 passing tests. No live service restart, commit or push was performed.


## Second optimization pass

Profile receipt: `output/replay-tape-benchmark-20260913/tape-next.prof`. The minute profile included preparation and is diagnostic, not an unprofiled latency result. Candidate source processing still built disposable public projections and repeatedly materialized broker components. Long runs also repeatedly fell back around dense same-timestamp cohorts.

- Exact tape phases now disable disposable intermediate DELTA/status construction inside ADVANCE_BY, while retaining the final post-commit snapshot, each trade reducer and source hash update.
- Planning remains bounded to 16 complete timestamp cohorts and now inspects at most 512 trades per track. The writer checks the full planned price envelope, including initial marks, against the current shared cash, signed positions, isolated allocations and maintenance tiers. It reuses the conservative interval screening function; a failed proof rolls back and uses scalar handling. Price bounds only authorize batching, never determine a liquidation or replace actual valuations.
- Added a same-millisecond crash-and-recovery liquidation test. The previous candidate could miss that intratimestamp risk interaction; the new envelope rejects the batch and the scalar coordinator observes it. Simply rejecting every changing-price cohort was correct but slow (12.90 s minute trial), so it was replaced with the conservative financial bound.
- All accepted cohorts still persist exact actor/source and review state. No trade-range index, endpoint valuation shortcut or native reducer is introduced by this pass.


### Second-pass qualification

| Same seeded BTC + ETH held workload | Previous pass | Second pass | Transactions before / after |
|---|---:|---:|---:|
| One 1m DISPLAY_BAR | 4.1398593 s | 3.6959046 s | 73 / 73 |
| One 1h DISPLAY_BAR | 504.4038871 s | 263.6527649 s | 12,943 / 2,376 |

The hour observation took 47.7% less wall time (about 1.91x throughput), and transactions fell by 81.6%. These are individual backend observations, not p50/p95 or browser measurements. The prior hour observation had the documented short test overlap; the second-pass measured command did not overlap our test runs. Opening took 3.235 s in the hour run and is separate from advance time. The hour remains slow at about 4 min 24 s; no instant-hour or day qualification is claimed.

Both windows consumed exactly the archive counts (minute 669 + 817; hour 41,386 + 41,759), and every final cursor matched the previous pass. The normalized whole portfolio matched, excluding the same derived revision/wall fields and combined hedge state hash documented above. Reopened-service account audits passed. BTC and ETH broker maximum drawdowns matched separately: minute 0.03837854 / 0.01145904; hour 0.5218 / 0.2122.

Evidence: `next-envelope-held2-1m/result.json`, `next-envelope-held2-1h/result.json`, and `next-envelope-qualification.json` under the benchmark output directory. `qualify_next.py` reproduces the account/cursor/count/drawdown comparisons and records implementation source hashes.

99 focused regression tests passed in 51.66 s. Added coverage includes dense same-time mixed-price trades beyond the former 32-event cap, scalar-equivalent financials/global order/max drawdown, and a same-millisecond liquidation excursion. Existing commit rollback, cancellation, restart and terminal-reply recovery checks passed. Ruff and diff whitespace checks passed. Production flags and the running service were not changed; changes remain uncommitted.


## Trade-summary substitution (2026-09-19)

The optimized tape coordinator now substitutes immutable candle aggregates plus
ordered maximum price fall/rise for dense, order-free trades inside a complete
same-timestamp cohort. Account state is not stored in the market cache (eight
bounded blocks). A safe dense block performs one final account calculation;
its prior peak and ordered price summary preserve both long and short drawdown.
The full shared-account price envelope is still checked under the writer lock
before any candidate is committed. Orders, funding/book dependencies, uncertain
risk and terminal boundaries retain the established exact fallback.

This is deliberately bounded to the existing 512-event plan and 16 complete
cohorts. It does not replace arbitrary minutes or hours with exchange OHLC.
Source decoding, validation, source-chain updates and cohort SQL/review writes
remain proportional to input/cohort counts. Sparse blocks use the existing
final-state reducer without disposable trade projections. Precision outside the
conservative exact Decimal domain also uses that reducer. A new diagnostic
`tape_summary_events` counts only events actually handled by dense summaries.
The probe's `reducer_events` counter counts calls to `apply_source_event`; it
excludes account work inside final-state blocks and is not an operation count.

The complete checkpoint comparison covers flat, long and short positions with
changing prices and partial candles. Tests require two final account calculations
for two summary applications covering 99 trades, and prohibit calls to the scalar
reducer. End-to-end comparison covers final financials, source chains, candle
state, global event ordering and account audit. Summary mode retains every equity
sample of the previous grouped mode. Existing scalar and grouped modes already
retain different EVENT sampling anchors; their time-resolution samples agree.
Rollback, cancellation, recovery and same-time liquidation excursions remain
covered by the tape regression suite.

An initial candidate invalidated component caches even for clock-only actors and
regressed minute latency. That candidate was corrected; its failed performance
trials remain in `summary-final-pair-*`. After the cache correction, serial paired
minute runs (same seeded BTC/ETH positions, no concurrent test run) measured:

| Repeat | Previous grouped path | Summary path | Transactions |
|---|---:|---:|---:|
| 0 | 3.854213 s | 3.703234 s | 73 / 73 |
| 1 | 4.256628 s | 4.198051 s | 73 / 73 |

These small samples show only a modest change, not a reliable latency distribution
or browser improvement. Every run consumed 669 BTC + 817 ETH trades. Full trade
reducer entry calls fell from 1,476 to 3; remaining valuation/source/storage work
explains why that reduction does not translate into a comparable speedup.

The final hour run took 267.836346 s, with 2376 transactions
and exactly 41,386 + 41,759 trades. Opening/preparation took
3.483480 s separately. The historical previous-pass receipt
was 263.652765 s: this does **not** demonstrate an hour acceleration, and it is
not a same-session paired hour comparison. No tests overlapped this measured
hour advance. This implementation leaves the existing global-cohort persistence
cost in place; a large cross-time jump still needs versioned review and curve
reconstruction, rather than dropping those anchors.

`qualify_summary.py` reopened every measured database and compared full broker
snapshot hashes, source-chain hashes, normalized portfolio, final cursors and
maximum drawdowns against each reference. All comparisons and account audits
passed. Hour drawdowns remained BTC 0.5218 / ETH 0.2122. Evidence and source hashes
are in `summary-qualification.json`; final cases use `summary-cachefix-*` under
`output/replay-tape-benchmark-20260913/`.

Validation: the broader focused set passed 113 tests in 76.64 s. After the
clock-only cache fix, the 27 tape/summary tests passed in 28.99 s. The final
14 summary tests (including empty candle gaps and raw trade counts) passed in
0.46 s. Ruff and diff whitespace checks passed. The optimization flag remains
unchanged, with no live-service restart, commit or push.


## Cross-time interval follow-up

The subsequent implementation replaces per-timestamp persistence with safe cross-time intervals. See [2026-09-19 interval qualification](replay-tape-interval-jump-20260919.md) for the 5–8 s hour observations, deferred curves and versioned review contract. This supersedes the limitation of the same-timestamp-only pass above.

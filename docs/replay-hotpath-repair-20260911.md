# Replay hot-path repair, 2026-09-11

Checkpoint storage and tape batching were subsequently completed in
[the durable-delta and multi-track follow-up](replay-durable-delta-and-multitrack-20260911.md).
The status below describes the earlier repair stage.

This repairs the follow-up working tree after `b19992bf`. It separates working
optimizations from unused prototypes and removes incorrect execution shortcuts.

## Correctness and actual integration

- Curve AUTO selection counts actual occupied buckets, including gaps. Interval
  endpoints can exclude old ranges, but do not imply continuous data. The service
  regression with two occupied 15-minute buckets separated by six hours selects
  15M and returns the exact two endpoints.
- Curve bodies load on demand according to the exact accumulated window. Basis
  restoration is reused between selection and valuation. Explicit-resolution
  warm reads also filter interval metadata at the SQL entry using the cached
  window; unknown legacy bounds remain eligible. Cold/AUTO metadata reads still
  depend on interval count.
- The production historical-book close method reuses validation of identical
  immutable depth. Every new command still checks its position and executes.
  Two separate half-position closes against unchanged depth both fill.
- Removed the unused independent-broker batching module. Its event-count ordering
  and unchanged-depth early return were not safe replacements for the service's
  global-time/account-event coordinator. Existing production multi-track and tape
  paths remain authoritative; this change does not broaden fast-path eligibility.
- Removed the unused broker delta checkpoint prototype and its suffix-only
  restoration branch. It embedded the full base and had no production writer.
  Full v1 broker snapshots remain the supported format. No delta snapshot was
  written by the production service through that prototype.
- Component encoding reuse remains active. Public snapshots recursively copy
  mutable component data so callers cannot poison cached encodings by changing
  nested order history. Snapshot copies and the final state hash still depend on
  retained history size; this is not constant-time checkpoint generation.

## Legacy preparation

Legacy account range summaries now use a market-only block tree instead of
scanning the entire requested range each time. A 9,884-bar summary test reads
fewer than 512 boundary rows after indexing and matches the linear reference.

Disposable preparation cache v5 stores source-chain seed/mode rather than forcing
all chain values. Its first save performs no source-chain hashing or account
sampling. Cache reload reinstates the original source-chain algorithm. A growing
legacy chain uses its contiguous cached prefix directly, removing the previous
quadratic scan of cached keys.

Prepared curve v2 stores market bars plus the account basis and chain seed;
registration no longer generates every future account sample or event hash.
Existing prepared curve v1 and shared curve v1 remain readable. Selected legacy
curve values and hashes are checked against the original scalar/chain formulas.

Exact legacy builder and event-chain reconstruction can still scan a span on
first advancement/read. Native shared ranges retain their separate bounded path.
Eliminating that compatibility work requires a versioned execution/storage
redesign; moving it to first advance is not counted as eliminating it.

## Evidence

Focused tests cover sparse AUTO selection, multiple interval windows, atomic
curve writes, cache reuse, background preparation, unchanged-book new commands,
snapshot alias isolation, full restore, ledger totals, range summaries, and
non-eager cache/curve registration.

Production service coverage includes historical L2 liquidation, account audits,
full-scan equivalence, multi-track cancellation at a global wave boundary, and
same-timestamp stop/cancel behavior. The broad run initially reported 127 passed
and one obsolete suffix-API test failure. That test now verifies failed full
restore leaves ledger entries and totals unchanged; its seven-test ledger suite
passes. Forty additional service/schema tests pass. The first new book test also
required fixture corrections (configuration placement, position-side construction
and initial bar index); no production behavior was relaxed for it.

Final clean core rerun: 79 passed in 110.68 seconds. The additional service/schema
run passed 40 tests in 10.12 seconds (119 distinct tests across these two suites).
After adding the interval-time SQL index, the 23 curve/schema compatibility tests
passed again in 4.28 seconds. Ruff and diff whitespace checks pass.

Synthetic service benchmark, 96,000 minute bars / 12 intervals:

| Query | Evaluations | Observed milliseconds |
| --- | ---: | ---: |
| 1H / 12 points | 12 | 36.335 |
| Same query | 0 | 20.433 |
| EVENT / 20 points | 20 | 5.147 |
| Same query | 0 | 2.615 |
| AUTO / 1600 returned points | 1588 new | 1368.812 |

Repeated queries wrote zero transactions. Evidence is
`output/replay-hotpath-repair-20260911-final.json`; rerun using
`python -m scripts.replay_curve_read_benchmark --output <receipt.json>` from
`backend`. These are single synthetic service observations during regression
work, not live-archive or browser speedup claims. An intermediate redundant
planning implementation measured 2461.960 ms for the large AUTO query and was
reworked; that earlier receipt is retained separately.

Training schema 22 adds nullable interval bounds; old rows use the compatible
fallback. Disposable cache v5 rebuilds prior cache versions. Prepared curve v2
requires this reader, so a code rollback must restore the pre-change database
backup. No live service restart, live database upgrade, commit or push was
performed as part of this repair.

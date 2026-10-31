# H127 minimum history interface — 2026-10-31

Result: the minimum **127-D / H127** interface passes local backend qualification.
This does not close #127 or qualify a new desktop release. R129 initialization,
mixed-source planning and history scheduling remain separate work.

## Revision and dependencies

- Stacked on B130 [PR #174](https://github.com/helenananaa/CandleScope/pull/174),
  commit `2182ead34e93047c1fcb10f0cfd3332ed78a6583`.
- Consumes D126 durable revisions/common budget and K130/B130 immutable
  summaries, leases, bounded retention and construction singleflight.
- Product/test source hashes and local test counts are in [checks.json](checks.json).
- The public market recording comes from the B130 latest-main native candidate
  `533b0a07a34e0924684f1bf29f946e9d4d71e8b9`; its original evidence is in
  [the B130 acceptance report](https://github.com/helenananaa/CandleScope/blob/f9eba489d8f4e4b9b32f75564970b7cbce6bb8f3/docs/qa/PR174_B130_20261031.md).
  This replay exports only 513 public OKX daily candles, not profile/account data.

## Results

| Check | Result |
| --- | --- |
| H127 tests with real temporary SQLite/DataManager | 63 passed |
| H127 + B130 focused regression | 155 passed (63 + 92) |
| Joint backend regression | 2,049 passed across 118 modules, 0 failures/errors/skips |
| Joint duration | 190.93 seconds; 27 existing deprecation warnings |
| Public recording: independent Decimal oracle | 104 blocks / 936 field comparisons passed |
| First cold page | 256 candle rows, one range read, 17 blocks |
| Repeated warm page | 0 candle-row reads, 17 / 17 block hits |
| Forward/backward traversal | Each covers all 513 slots exactly, in three bounded pages |
| Amendment / delete | Each rejects the previous continuation revision |
| Delete quality | Exact deleted slot reported unavailable, no false complete page |
| Shutdown | 0 entries, retired entries, views, leases, flights, charged block bytes and reserved bytes |
| Standalone fixture replay | Passed again without access to the original database |

The oracle reduces the captured rows independently with Decimal and the existing
eight-decimal input normalization contract. It checks all nine OHLCV/enhanced
fields, preserving unknown values. Numeric tolerance remains absolute `1e-8`
or relative `1e-12`; it does not compare the reducer to itself. The checked-in
[recording receipt](recording.json) records inputs, ranges, revision vectors,
field errors, I/O and resource counts. Timings include oracle work and are not
a claim about application speedup or cold-network performance.

The tests cover invalid or unknown sources/calendars, both pagination directions
and varied sizes, raw row bounds, trusted finality, unknown fields, storage
errors, budgets, retained page handles, independent consumers, external SQL,
empty deletion, rollback, storage rebind and source changes during publication.
Two coordinated cold readers verify one shared block construction and isolated
owner/joiner cancellation. They perform **two** candle reads; this stage does
not claim cold I/O/decode coalescing. Revision checks may still perform SQL on
a warm page.

## Reproduction

From the repository root, using the project's Python 3.12 environment with its
pinned CCXT fork and test dependencies:

```sh
.venv/bin/python docs/qa/h127-20261031/run_backend.py
.venv/bin/python docs/qa/h127-20261031/recording_probe.py
```

The first command uses the explicit [118-module list](joint-files.json), an
isolated data directory and a 90-second per-test timeout. XML is written below
`output/h127-reproduction/`. The second command replays
`public-okx-daily.json.gz` into a new temporary SQLite database; all amendments
and deletes affect that database only. Its receipt is written under the same
output directory. Input capture, when explicitly needed, uses `--source-db`
with a read-only SQLite connection.

## Scope and next handoff

The [interface contract](../../architecture/HISTORY_BLOCK_READER_H127.md) defines
qualified default Binance/OKX native fixed grids from 1m to 1d, a maximum of
256 expected slots per page, post-exit receipts, and explicit error/cancellation
behavior. Time passing never creates trusted finality. Unavailable coverage is
not proof of a provider gap; ending a requested range is not listing exhaustion.

R129 can now consume this interface for staged historical-prefix construction,
but must apply its own revision/generation fence at adoption and own live-overlay
handoff. H127 does not write target materializations, start backfill or introduce
another cache, durable ledger or scheduler. A successful read receipt is not
proof that a target was adopted or persisted.

Cloud CI runs normally after pushing. It is **not awaited for this development
PR** under the user's current workflow. Required checks and fresh integration
evidence must be assessed before any eventual merge into main. No main merge or
desktop installation is part of this H127 delivery.

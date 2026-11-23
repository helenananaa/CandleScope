# WIP — coarse qualification and cold admission audit

Base: `ec3eb0ece1b978dfe3071e7c8635ea51e1723521`, after merged PR #410.
This candidate is not delivered or qualified. Frontend admission is unchanged.

The six official BTCUSDT USD-M October 2026 archives and matching SHA256 checksum
files were downloaded. The previous four hashes were retained; 4h/1d hashes
were verified and pinned in the downloader. `evidence/inputs.json` records URLs
and hashes. The first 16 complete days were compared using the existing Decimal
oracle and tolerance contract: 16 daily and 96 four-hour bars matched all nine
raw aggregation fields exactly (maximum Decimal difference zero). Existing
1h/15m/5m/1m comparisons also passed. The actual H127 reader completed 55 target/
page comparisons against the same oracle. This is recorded public data, not
live cold-start or universal per-range availability proof.

The uncommitted adapter candidate extends the existing default-trade/base,
fixed-UTC USD-M composition grids to include 4h/1d, with evidence references.
No other provider, identity or calendar is admitted. New default-planner/SQLite
regression: 128 x 10007m formerly declined `source_row_budget`; the candidate
fits the same 16,384 source-row budget. The default query/planner selection
passed 52 tests, but broader verification is not green yet.

`plan-cost.py` runs the real default planner on new empty SQLite databases, with
no network fetch. Its retained baseline/candidate reports show:

| Target count | Existing four grids | Six-grid candidate |
| --- | --- | --- |
| 1 | 171 rows, 3 proposed REST requests | 18 rows, 5 requests |
| 8 | 1395 rows, 36 requests | 177 rows, 59 requests |
| 128 | Declines source-row budget | 2931 rows, 973 requests |
| 406 | Declines source-row budget | Declines task work budget |

These are planned counts, not measured physical network traffic. Single-run
process CPU observations are unpaired and include initialization: they are not
stable latency measurements. Candidate planning for 128 spent about 14.8 CPU
seconds; the rejected 406-target proposal spent about 64.4 CPU seconds. This
exposes planning/work-accounting cost and means a frontend budget-only change
would not establish acceptable cold-first-screen behavior.

The broader pipeline probe currently has **6 failures / 68 passes / 5 warnings**:
four transport cases observe changed request counts (5 instead of 3 at batch
1000, 5 instead of 8 at batch 32); one expects the old three interval names;
one streaming stress case now has only 13 rows in its largest page rather than
exercising a full 256-row page. Do not simply relax these assertions: preserve
meaningful network-cost and actual large-page stress coverage. Assertions after
those failures have not all been reached. The initial mistyped test path ran
zero tests and is retained separately, with no validation claim.

Next work must compare feasible cold plans by real request/quota cost while
keeping bounded planning work, preserve the small-request behavior or explicitly
justify its tradeoff, and retain large-page streaming checks. The 10007m
frontend guard remains unchanged until backend execution/admission can support
it safely. No new native run has tested this six-grid candidate. #126/#127/#129
remain open; #130 remains closed. All failed/successful evidence and profiles
from the previous batch remain preserved.

Official archive provenance and field layout are described by
[Binance Public Data](https://github.com/binance/binance-public-data).

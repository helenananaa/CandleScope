# Qualified USD-M cold history planning

Base: `ec3eb0ece1b978dfe3071e7c8635ea51e1723521` (merged PR #410).
Planner runtime: `e08bd3233`; composed viewport runtime: `d78c7d46a`.
The original development audit and failed probes remain preserved separately.

The existing USD-M default-trade/base, fixed-epoch UTC composition declaration
now qualifies 1m/5m/15m/1h/4h/1d grids. No other provider, identity or calendar
is admitted. Qualification does not prove availability of an individual range.
The six official BTCUSDT October 2026 archives have pinned SHA256 checksums in
`evidence/inputs.json`. The existing Decimal oracle compared the first 16 complete
days across all six grids and all nine aggregation fields: maximum Decimal
difference zero. The real H127 reader passed 55 target/page comparisons under
the existing tolerance (relative 1e-12, absolute 1e-8). This recorded data is not
live cold-start, all-symbol or universal historical qualification.

Cold proposals compare bounded grid subsets by proposed REST pages, then rows.
The search consumes a shared position budget, releases each small cover batch,
and reuses the original executor for the selected proposal. Existing canonical
reads, finer precedence, revision/delete fences, admission and writer decide
actual adoption. This is a bounded heuristic rather than a global optimizer.

| 10007m targets | Previous four grids | Six grids, all greedy | Bounded cold choice |
| --- | --- | --- | --- |
| 1 | 171 rows / 3 requests | 18 / 5 | 669 / 2 |
| 8 | 1395 / 36 | 177 / 59 | 5376 / 24 |
| 128 | Source budget decline | 2931 / 973 | 14670 / 493 |
| 406 | Source budget decline | Late task budget decline | Early task budget decline |

These are planner proposals on new empty SQLite databases, without network.
The selected candidate intentionally trades extra rows for fewer requests.
Loopback with the real pinned CCXT stack independently verifies complete target
values and actual calls: a one-target request uses 2 calls at batch 1000
(previously 3), or 4 at batch 32 (previously 8). Only actual fine rows are stored;
coarse coverage never fabricates fine persisted coverage. The canonical-stream
stress fixture now still exercises a full 256-row page under the larger grids.

The existing plan builder accounts retained task roots incrementally and
remeasures mutable gaps/presence. Transient roots are excluded from its seen set;
retained roots and conservative seen-set overhead remain charged to the original
4 MiB work budget. No new cache, writer, scheduler or revision ledger is added.
The 128-target plan's recorded high-water work estimate is 1,385,804 bytes.
Single unpaired CPU observations decreased from about 8.92 to 2.52 seconds for
that plan; these are not latency percentiles or whole-application improvements.

The frontend uses the existing source-aware scheduler, which splits the larger
history demand into bounded jobs. See `../mixed-history-viewport-127-20261114`
for explicit contract binding, product-flow observations and final checks.
Direct oversized repairs can still decline: this does not claim arbitrary
request completion, all-provider rollout or closure of #126/#127/#129.

Archive provenance and field definitions: [Binance Public Data](https://github.com/binance/binance-public-data).

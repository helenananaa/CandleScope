# Pine chart orders

The chart strategy runner negotiates `ORDER_INTENT` for newly compiled Pine
strategies. Both direct runs and automatic data preparation carry that mode.
The API also retains `TARGET_POSITION` for the existing one-entry market-order
profile. New order-mode envelopes freeze `candlescope.pine-orders/1`; they need
a matching Host implementation identity before execution or recovery.

The Pine interpreter produces decisions. The Host's existing kernel admits and
matches orders, and its account supplies every subsequent Pine observation.
Cash, fees, profit and the net average-cost position come from that account.
Script entry IDs allocate quantities through
`HOST_NET_AVERAGE_COST_ENTRY_QUANTITY_FIFO_V1`.
For spot accounts, Pine net profit excludes cash exchanged for held inventory;
the adapter derives realized net profit from equity minus initial capital and
unrealized profit, as the workbench account adapter already does.

Supported chart orders include:

- market, limit, stop and stop-limit entries;
- up to 64 pyramiding entries, subject to Host risk and account admission;
- ID-specific quantity/percentage closes and close-all;
- absolute-price or tick-distance OCO exits, including brackets submitted
  before an entry fills;
- cancellation and replacement of pending script order IDs; and
- trailing stops on an ordered trade execution clock, with an explicit tick.

`BAR_APPROX` keeps the Host's approximate OHLC fill policy. Aggregate-trade
execution evaluates completed signal bars and matches against subsequent trade
prints. It can advance a trailing stop between signal-bar evaluations.
`calc_on_order_fills` additionally negotiates
`candlescope.pine-fill-callbacks/1` with the installed `pine-chart/2` adapter.
This profile requires `ORDER_INTENT` and `AGG_TRADE_EXECUTION`; incompatible
BAR or target-position runs are rejected before execution. Each actual fill
updates logical entry ownership before the next Pine observation. The callback
receives the actual account and only OHLCV incorporated from observed prints.
Its newly submitted orders become eligible on the next aggregate-trade event,
including a later event with the same millisecond timestamp.

Fill passes and the confirmed close have separate monotonic observation
sequences. The provider retains each pass's account, clock, confirmed flag and
requested-data prefix. Auxiliary bars closing in the same millisecond as a
fill remain hidden until the close has consumed the full cohort. Foreign symbol
metadata belongs to the outer registry; pass streams contain only symbol,
timeframe and visible bars. Checkpoints can restore an unconfirmed pass group.
`strategy.pineExecution` in the report identifies this causal execution profile
and counts observed bars and fill callbacks.
At a signal boundary, the Host closes the preceding trade-derived bucket before
applying later mark, funding or instrument-rule events. An auxiliary event can
confirm that bucket before the next trade arrives. Checkpoints preserve that
confirmation, while aggregate-trade gap and late-print guards remain active.

This is a causal Host replay contract. TradingView documents that its historical
`calc_on_order_fills` executions can read a bar's final OHLCV, while realtime
executions see developing values. CandleScope's observed-print callbacks do not
claim equivalence to that historical broker-emulator behavior. See the official
[strategy execution documentation](https://www.tradingview.com/pine-script-docs/concepts/strategies/#calc_on_order_fills).

`calc_on_every_tick`, `calc_on_every_history_tick`, `process_orders_on_close`,
`strategy.order` and Pine `strategy.risk.*` still require further integration or
core capability work. The current runtime rejects unknown declaration options.

The Host validates order batches and rechecks risk when a pending order becomes
executable against the live ledger. Script IDs bind to actual accepted order
receipts using a Host-generated client tag. Rejection of an earlier submission
cannot shift the ownership of a later accepted order.

Checkpoints include the provider's causal history, kernel state, Host policy
state and order ownership/allocation state. Pending submission tags are also
retained for clocks that freeze a decision before order admission. The report's
`pine_orders` section exposes the logical entries and fill allocations.

Pine rich-order cost sensitivity currently returns the explicit status
`PINE_ORDER_RESIMULATION_REQUIRED` instead of applying the generic frozen-order
matrix. Relative exits and fill-dependent decisions require independent Host
allocation and script feedback in every cost scenario; replaying placeholder
prices or baseline callback decisions would produce invalid comparisons.

Validation uses the actual installed interpreter, HTTP run creation, queued
workers, automatic preparation, a durable interrupted/resumed run and an
aggregate-trade trailing-stop case. The callback cases also cover per-fill
ownership, requested-data boundaries, and interruption after a durable forming
pass. Logs live under `output/pine-host/phase3/chart-fill-*.log` and
`output/pine-host/phase3/rich-chart-*.log`. These are controlled fixtures; current
work does not establish arbitrary TradingView broker-fill or live-tick parity.

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
`calc_on_every_tick`, `calc_on_order_fills`, `process_orders_on_close`,
`strategy.order` and Pine `strategy.risk.*` still require further integration.
Selected rich workbench callback tests do not qualify those chart options.

The Host validates order batches and rechecks risk when a pending order becomes
executable against the live ledger. Script IDs bind to actual accepted order
receipts using a Host-generated client tag. Rejection of an earlier submission
cannot shift the ownership of a later accepted order.

Checkpoints include the provider's causal history, kernel state, Host policy
state and order ownership/allocation state. Pending submission tags are also
retained for clocks that freeze a decision before order admission. The report's
`pine_orders` section exposes the logical entries and fill allocations.

Validation uses the actual installed interpreter, HTTP run creation, queued
workers, automatic preparation, a durable interrupted/resumed run and an
aggregate-trade trailing-stop case. Logs live under
`output/pine-host/phase3/rich-chart-*.log`. These are controlled fixtures; current
work does not establish arbitrary TradingView broker-fill or live-tick parity.

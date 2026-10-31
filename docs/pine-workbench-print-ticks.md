# Workbench Pine on observed print and book clocks

`calc_on_every_tick=true` strategies negotiate `candlescope.pine-print-tick/1`
for `TRADE_TAPE`, `BOOK_ASSISTED`, `BOOK_DEPTH` and `BOOK_SAMPLED`. The exact
frozen tape must reproduce the selected chart OHLCV. Book observations update
the existing matcher; they do not invent a chart price or an additional Pine
tick. One explicit realtime strategy observation follows each actual print's
matching. Newly created orders wait for a later print. Fill reports still update
Host ownership and accounting without duplicating that print's Pine execution.

Opening sends the first observed tuple without future chart/account data. Each
step sends one observation and receives only its new intents. Requested feeds
advance at the actual inclusive source timestamp, with append-only deltas;
providers without the observed-data contract remain explicitly rejected.
Bucket confirmation is a separate explicit close observation after its prints.
The simulated closing option retains the existing book/depth/capacity policies
and provides explicit consecutive closing-fill feedback when requested.

V1, spot and V2 accounts retain their own admission and settlement rules. V2
marks come from historical MARK_INDEX, and funding/account events precede market
events on timestamp ties. Such events update the account without creating a
synthetic price tick. Independent cost scenarios use fresh streams, accounts
and the same market clock, including participation controls where the existing
physical model supports them.

Durable checkpoints remain completed chart bars. Their clock, actual account
frames and intent history must match the recorded stream observations. Recovery
verifies every replayed response and emitted intent before restoring the Host
ledger. Live replay workers reuse an exactly matching checkpoint; seeking,
eviction or process restart reconstructs the evaluator without matching old
market events again. Cancellation, deadlines and the two-worker bound remain
in force. This does not restore unrecorded events from a live exchange session.

These are controlled frozen-source-stream executions. They do not qualify
arbitrary TradingView scripts, raw trade reconstruction from aggregate trades,
exchange queue position or actual close-auction liquidity. Dynamic historical
window discovery, long-history resources, connected live subscriptions and the
formal packaged binary retain their own qualification.

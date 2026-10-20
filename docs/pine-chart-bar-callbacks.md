# Historical chart BAR fill callbacks

Chart `PINE_ENGINE` strategies with `calc_on_order_fills=true` can now run
`BAR_APPROX` in `ORDER_INTENT` mode using the existing V1 linear account or spot
cash account. The compiled adapter must negotiate the explicit execution
schedule. The Host derives and freezes `pine_bar_path_contract`; a caller
cannot turn an ordinary source into a callback strategy by supplying that
private field.

`PineChartBarKernel` supplies chart lifecycle and source cursors over the
shared `PINE_OHLC_PATH_V1` matcher. The chart planner still owns admission,
entry allocations, OCA, cash/fees and risk enforcement. Its order adapter
selects the path profile, including trailing activation, rather than applying
the legacy whole-bar assumptions. Workbench and chart matching share the
same price path and fill bookkeeping.

Three clocks have separate roles: source sequence identifies the durable
chart-bar cursor; path sequence controls order eligibility and market
opportunities; provider sequence increases for every script observation.
Snapshots preserve both kernel cursors and the provider's explicit schedule.
Restore checks source/observation counts before any new matching.

Historical callbacks supply completed canonical OHLCV and the actual
post-fill account. `historical/order_fill` observations do not commit the
bar; `historical/bar_close` commits it. An enabled simulated close can then
emit `historical/closing_fill`. Historical script confirmation remains true
throughout. Provider frames use the canonical close as historical knowledge
watermark, while execution timestamps retain the synthetic path time.
Requested data uses the historical close cutoff with foreign metadata intact;
the legacy aggregate-trade profile retains its causal print cutoff.

The regular service entry point, queued/supervised execution, warmup,
checkpoint publication and report sealing all use this path. Warmup advances
the script without submitting its orders. Complete bars are durable; if a
process stops after an intrabar fill but before its bar commits, recovery
restores the preceding complete bar and reconstructs that bar's account and
script observations together. This phase does not add public seeking or
durable checkpoints inside a historical path leg.

Cost sensitivity independently reconstructs the baseline, then reruns the
actual Pine program and Host account for each fee/slippage scenario. It
checks primary versus fresh-baseline hashes, orders, curve and planner state.
V1 OHLC matching has no physical volume capacity. Participation and source
latency scenarios therefore carry explicit not-applicable statuses instead
of pretending to reduce observed tape liquidity. A fee-dependent callback
test verifies that higher costs change the exit order and its actual price.

Timeout/cancel cleanup now serializes competing worker closes. Terminated
Windows pipe-close errors are recorded while the remaining streams are still
released, preserving the original timeout/cancel diagnostic. The Pine provider
detaches its worker before closing it, so concurrent cleanup cannot reuse it.

Reports identify the path contract, synthetic timestamps and absent physical
tape. This implements historical BAR callbacks for V1/spot; it does not prove
TradingView output equivalence. The path's low-first tie policy and synthetic
interpolation remain declared assumptions. V2 margin/mark authority and shared
participation capacity are now connected through the separate model in
`pine-v2-bar-path.md`. BAR latency remains not applicable under its declared
API. Realtime ticks, history-tick declarations and magnifier scheduling remain
goal work.

See [the shared path model](pine-bar-path.md) and the
[official strategy execution documentation](https://www.tradingview.com/pine-script-docs/concepts/strategies/).

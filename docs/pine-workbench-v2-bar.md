# Workbench V2 historical BAR API

The `POST /backtests/external/runs` Pine profile can now select the same
`candlescope.pine-v2-bar/1` matcher used by chart callbacks. The interpreter
continues to emit intents and consume actual Host feedback; it never owns a
second trading account. Existing V1/spot requests keep their matcher.

Use `execution_fidelity="BAR_APPROX"`, `fill_recalculation=true`, and a script
declaring `calc_on_order_fills=true`. `account_model="LINEAR_PERP_ONE_WAY_V2"`
selects the historical perpetual account, with `leverage` and `funding_mode`
(`OFF` or `HISTORICAL_REQUIRED`). Supply `account_data` with this shape:

```json
{
  "symbol": "BTCUSDT",
  "events": [
    {"time_ms": -1, "role": "MARK_INDEX", "payload": {
      "mark_price": "100", "index_price": "100"
    }}
  ],
  "provenance": {"source": "your frozen historical dataset"}
}
```

The example illustrates the envelope only. Actual data also requires historical
`INSTRUMENT_RULES` covering the first open, including multiplier, tick, quantity
step, minimum notional and maintenance tiers. Funding mode requires historical
`FUNDING` events with rates and distinct period IDs. Missing roles, wrong symbols,
unordered events and observations beyond the chart horizon reject before matching.
Events at the same timestamp retain input order, before the canonical BAR close.
No mark, rule, rate or liquidity is fetched from the network or invented.

`execution_model_revision="EXECUTION_REALISM_V2"` additionally requires
`participation_rate` in `(0, 1]`, and selects
`bar_path_scenario="OHLC_NEAREST_EXTREME_PATH_V2"`. It can be used with V1,
spot or V2 accounts. Capacity is one shared `volume * participation_rate`
budget per bar, including callback and closing orders. V2 accounting without
execution realism remains uncapped. Print/book execution keeps its existing
profiles; it cannot silently accept these new BAR settings.

The frozen input binds account events, settings and provenance. Actual worker
requests contain only the causally observed account feedback, without forwarding
the future account-event tape. Replay snapshots bind the chart count, raw source
cursor, logical path cursor, account ledger, allocation and evaluation transcript.
Restoring and continuing does not repeat earlier fills, funding or settlements.

The API and durable replay route are connected. The Workbench settings UI still
needs controls/import for these fields. Independent cost matrices on this route
also remain open; the chart route has separately qualified cost reexecution.
The synthetic OHLC path, volume proxy and declared CandleScope liquidation model
do not establish TradingView equivalence. Nonunit Pine metadata remains rejected.
Working-order margin repricing across large price gaps remains account-model
work: a retained diagnostic reproduces negative available balance after partial
fills under stale marks; the current account rejects the run rather than silently
continuing with an invalid ledger. Realtime/history-tick and other remaining work
in `pine-host-completion-goal.md` remain active.

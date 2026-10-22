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

The API, durable replay route and Workbench settings now connect these fields.
Pine BAR fill callbacks remain enabled through both direct and automatic-preparation
submission. The UI offers account, leverage, funding, account-file import and
volume participation controls. Drafts retain parameter values and an upload
marker, rather than the event tape; reopening requires file reselection and marks
the old result stale. Changed callback settings or account data also invalidate
the old result. Static account/capacity validation is shared with automatic
preparation, before its market-data acquisition.

V2 freezes its opening price grid from the historical account rules before
compiling Workbench controls. Explicit conflicting chart metadata rejects;
the generic matching tick cannot override the historical grid. Relative and
trailing Host prices read actual account rules. The opening historical rules also bind linear point value, exact quantity step
and independent minimum through the bounded [contract profile](pine-contract-rules.md).
Nonunit linear multipliers are supported. Point value and the chart price grid
must remain fixed within one frozen run; historical account admission continues
to consume the observed rule events.

Controlled browser qualification mounts the actual Workbench panel and submits
to an isolated real backend/Pine worker. It is not a packaged-app release or an
exchange-data acceptance test. Independent complete-endpoint Workbench cost
matrices now reexecute Pine and fresh Host accounts (`pine-workbench-costs.md`),
with an explicit SKIP control and replay endpoint verification.
The synthetic OHLC path, volume proxy and declared CandleScope liquidation model
do not establish TradingView equivalence.
Working-order margin now reprices causally across price gaps, retaining booked
fills and cancelling unfunded remainders under the declared CandleScope policy;
see `pine-v2-margin-repricing.md` for collateral, maintenance and replay boundaries.
Realtime/history-tick and other remaining work
in `pine-host-completion-goal.md` remain active.

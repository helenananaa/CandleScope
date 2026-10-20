# Pine historical BAR matching and Workbench fill recalculation

The Workbench `CANDLESCOPE` account path now admits `BAR_APPROX` with
`fill_recalculation=true` when the source enables `calc_on_order_fills`, the
adapter exposes Workbench controls, and it negotiates
`candlescope.pine-execution-schedule/1`. Admission freezes
`candlescope.pine-bar-path/1` into the input. Older adapters and sources without
the required setting retain explicit rejection.

The matcher is `PINE_OHLC_PATH_V1`. It visits the nearest extreme first, then
the other extreme and close, matching price-order crossings along each leg.
Orders crossed during the interbar gap fill at the next open. Stop-limit
activation precedes limit eligibility. Stop/target OCO follows the path; it
does not use the legacy whole-bar stop-first scan. Relative brackets bind to
actual entry allocations. Trailing activation and favorable watermarks are
visited before reverse stop crossings. Callback orders cannot consume their
creation point; market orders wait for the next OHLC vertex. Equal-distance
bars use low first as a declared local policy.

Every fill uses the existing Host ledger, fees, cash checks, allocation, OCA
and Pine risk controller. Historical callback frames contain the completed
canonical OHLCV and the actual post-fill account. They carry explicit
`historical/order_fill` context, with observation commit false. The normal
bar-close evaluation commits the bar. An enabled simulated closing tick
follows it; any resulting callback uses `historical/closing_fill` and the same
close observation. New orders from that callback await a future point.
Historical `barstate.ishistory`, `isconfirmed` and `isnew` remain true during
fill callbacks; commit markers no longer impersonate script bar state.

Requested streams use the canonical chart-close visibility cutoff throughout
historical recalculation, independently of synthetic path time. Foreign symbol
metadata remains in its original context. This is separate from the causal
observed-print visibility of the existing trade-tape clock.

The path has its own monotonic sequence and checkpoint identity. Workbench
replay restores complete chart bars, Host ownership/risk state and the exact
explicit evaluator transcript. Reconstruction never rematches previous fills.
The legacy matcher rejects path snapshots. Report hashes and `fill_model`
distinguish the new model; existing noncallback BAR runs keep their previous
model. `raw_output.execution_schedule` records context and evaluations, while
`execution_passes` retains the parallel evaluation-only report.

## Qualification boundaries

This phase connects Workbench historical fill recalculation for the existing
linear V1 and spot cash accounts. Chart BAR callbacks, V2 path integration,
realtime ticks, `calc_on_every_history_tick`, magnifier scheduling, larger
history performance and packaged product acceptance remain goal work.

No physical trade tape is inferred. OHLC vertices are assigned thirds of the
bar interval; crossings receive linearly interpolated **synthetic** timestamps.
The disclosure explicitly reports this policy and
`official_oracle_verified=false`. Volume participation and real intrabar
liquidity are not inferred. Fees, slippage and current account restrictions
remain the Host model's policies.

Path and historical fill visibility were checked against the current
[TradingView strategy documentation](https://www.tradingview.com/pine-script-docs/concepts/strategies/),
especially broker assumptions and `calc_on_order_fills`. This is documentation
alignment, not fresh official output equivalence for tie cases, tick ordering,
requested-data timing, commissions, pyramiding, margin or partial fills.

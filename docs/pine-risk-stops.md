# Pine risk stops through the Host matcher

The chart `ORDER_INTENT` adapter supports `max_drawdown`, `max_intraday_loss`,
`max_intraday_filled_orders` and `max_cons_loss_days` through
`candlescope.pine-risk-stops/1`. It requires risk configuration schema 1 from the
interpreter. The older entry-only handshake continues to authorize only entry
direction and position-size constraints. Workbench external-account risk stops
remain unconnected and reject; the chart implementation must not be advertised
as that separate execution path.

The interpreter discovers declarations independently of branch execution. The
Host freezes every rule, including duplicate rules, and observes the real ledger
without running the script on each market event. BAR, aggregate-trade, mark/index,
funding and explicit simulated closing-tick paths feed the stop controller.
Fills update the same state after actual ownership allocation and before any
script fill callback. Global and intraday equity peaks, completed realized-loss
sessions, first-filled order IDs, permanent/window halts and alert text are
preserved through checkpoint restore.

At a trip the Host cancels live script orders and submits one reducing market
close against the actual net position. That close uses the existing matcher,
account admission, source capacity, quantity constraints and latency. It cannot
reuse the tick that created it. A simulated close after an earlier physical
print may be the next matching tick, but a stop created during a simulated close
must wait for another tick. Partial risk closes retain their ownership and
remaining size through recovery. Script orders, including generic orders and
cancellations, are suppressed while halted or while liquidation remains pending.
There is no fabricated fill or guaranteed unlimited liquidity.

Reports expose `pine_risk_stops`: the declared window policy, trips, submitted
close actions, halt status, pending liquidation and actual residual position.
Capacity exhaustion, rejected closes and end-of-data residual inventory remain
visible. Alerts are retained as metadata; external alert delivery is separate.
Each cost scenario recreates the interpreter, allocator, stop state and matcher;
it does not reuse primary-run stop decisions or financial state.

## Calendar and fidelity boundaries

Maximum drawdown needs no session calendar. Windowed rules currently require
explicit Binance spot/USDM/futures/swap market metadata, with the continuous UTC
trading-day contract recorded in the run identity. Unknown-market calendars
reject before execution. On chart timeframes above one day, intraday rules use
explicit chart-bar windows. Consecutive-loss-day rules on multi-day BAR data
reject because daily realized account observations cannot be recovered from a
weekly/monthly OHLC bar. Missing intervening trading sessions also reject rather
than inventing daily PnL. Other venue calendars remain a Host integration gap.

The current fill-count convention counts an order once per intraday window,
beginning with its first positive partial fill. Later partials still update
financial state. Risk-generated closes do not recursively count as script
orders. This convention needs an official partial-fill differential oracle.
Automatic V2 account liquidation remains an open ownership-receipt gap. A
controlled mark-price liquidation reproduced account position 0 with allocated
Pine quantity 50. The candidate now raises
`EXTERNAL_LIQUIDATION_RECEIPT_REQUIRED` at that boundary instead of publishing a
completed report with stale allocations. This is a temporary explicit rejection,
not completion of liquidation integration. Mapping the actual account settlement
into ownership/fill evidence, callbacks and recovery remains required goal work.
The reproduction is retained in
`output/pine-host/phase3/risk-stops-v2-liquidation-gap.json`.

BAR risk observation follows the Host BAR approximation; it does not reconstruct
an official historical four-tick or lower-timeframe broker-emulator path. V2
unrealized equity follows the authoritative Host mark/index account model.

The core resolver still admits a bounded set of immutable scalar expressions
and positive numeric limits. Zero-limit boundary semantics, arbitrary session
calendars/lot steps, official broker-fill equivalence and native-account risk
registration/aggregation remain separate work. The default task environment is
unchanged; the stop candidate has its own runtime registry and installed wheels.

The official [risk-management documentation](https://www.tradingview.com/pine-script-docs/concepts/strategies/#risk-management)
defines every-tick/order-execution checks and stop actions. The
[earlier detailed strategy documentation](https://www.tradingview.com/pine-script-docs/en/v4/essential/Strategies.html/#risk-management)
also describes same-kind rule precedence and intraday windows above one day.
These inform the implementation; controlled tests are not a fresh TradingView
output oracle or packaged-app acceptance.

## Development evidence

The complete pre-optimization Host group passed 328 cases, with 41 non-Pine or
optional-profile cases deselected. A later change limits halted-stop processing
to the existing active-order index; the regression reproduces 20,200 historical
row visits before that change. Its subsequent focused real-Pine group passed
55 cases, and the final kernel/account/state group passed 126, including the
explicit liquidation-receipt rejection. Production-source snapshots distinguish
these phases; the 328-case run is not represented as including the later changes.

Bridge checks passed 73 cases with 12 optional Renko-extension skips. Frontend
typechecks and 226 backtest tests passed; technical report details expose the stop
audit. Installed bridge files match source bytes. The core binary is unchanged
from qualified revision 1b506560a, with its retained 7,912 Rust/1,731 Python/172
tooling checks. These remain controlled development checks, not packaged-app or
TradingView differential qualification. The first long Host run was deliberately
cancelled after the funding-boundary defect was independently reproduced; its
partial log, process receipt and failing probe remain retained.

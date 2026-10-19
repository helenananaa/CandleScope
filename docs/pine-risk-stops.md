# Pine risk stops: state and execution integration

The Host state machine in `backend/app/backtest/pine_risk_state.py` implements
the state transitions for maximum drawdown, maximum intraday loss, maximum
intraday filled orders and consecutive realized-loss days. It consumes actual
equity and net profit supplied by the Host ledger. It never maintains another
account, executes a strategy, acquires a calendar or fills an order.

This component is not yet wired into market/funding/fill observation or order
cancellation/flatten scheduling. All four commands remain rejected by the
chart adapter. State-machine tests alone do not qualify stop execution.

The state tracks independent same-kind declarations, global and intraday equity
peaks, permanent and window-scoped halts, completed realized-loss sessions,
first-filled order IDs, alert metadata and a causal observation clock. A
nonpositive equity observation with a percentage stop creates a permanent halt.
Checkpoint restore freezes the configuration, initial equity and window policy.

Windowed rules require explicit monotonic Host window ordinals. Session gaps for
consecutive-loss rules reject until intervening sessions are settled explicitly.
The caller must provide a real calendar contract, including the separate
per-chart-bar intraday window for chart timeframes above one day. The component
does not silently infer a UTC trading day. Missing session metadata remains a
Host capability gap.

Current fill-count state counts an order once in each intraday window beginning
with its first positive partial fill. Later partials update equity and realized
PnL without increasing that count. Risk-generated closes omit the script order
ID so they do not recursively increase the count. This convention needs an
official partial-fill differential oracle before equivalence can be claimed.

Remaining execution work includes observing every market/account update and
fill even without script calculations or pending orders, cancelling outstanding
orders at a trip, scheduling a reducing market close with the real Host
liquidity/latency limits, suppressing script orders while halted or while a
forced close remains pending, and preserving all state through callbacks,
cost-scenario reexecution and durable recovery. End-of-data residual positions
and capacity exhaustion must remain visible in the report.

The official [risk-management documentation](https://www.tradingview.com/pine-script-docs/concepts/strategies/#risk-management)
defines the all-ticks/order-executions requirement and stop actions; the
[earlier detailed strategy documentation](https://www.tradingview.com/pine-script-docs/en/v4/essential/Strategies.html/#risk-management)
also describes same-kind rule precedence and intraday windows above one day.
These documents inform the implementation; no fresh TradingView oracle has
qualified the Host state or execution paths.

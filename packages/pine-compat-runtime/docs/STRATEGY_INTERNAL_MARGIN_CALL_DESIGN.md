# Strategy Internal Margin Call Design

Closed on 2026-06-03.

This note closes Strategy Internal Margin Slice M4 from
`docs/STRATEGY_INTERNAL_MARGIN_ACCOUNT_MODEL_PLAN.md`. It is a design gate for
the M5 implementation; it did not enable forced liquidation by itself.

Official reference:

- TradingView Pine Script strategies, Margin section:
  <https://www.tradingview.com/pine-script-docs/concepts/strategies/#margin>

## Scope

Implement the first liquidation subset only for the current broker model:

- one net long position;
- explicit active `margin_long`;
- no shorts, reversals, pyramiding, or per-entry open-trade ledger;
- no `strategy.margin_liquidation_price` variable yet;
- no public CLI JSON, Python dictionary, or WASM JSON schema expansion.

## Official Algorithm Mapping

TradingView documents margin-call liquidation as:

1. `Money Spent = Quantity * Entry Price`
2. `MVS = Position Size * Current Price`
3. `Open Profit = MVS - Money Spent` for longs
4. `Equity = Initial Capital + Net Profit + Open Profit`
5. `Margin Ratio = Margin Percent / 100`
6. `Margin = MVS * Margin Ratio`
7. `Available Funds = Equity - Margin`
8. `Loss = Available Funds / Margin Ratio`
9. `Cover Amount = TRUNCATE(Loss / Current Price)`
10. `Margin Call Size = Cover Amount * 4`

For the current long-only runtime, map those terms to existing broker fields as
follows:

- `Quantity`: `position_size`
- `Entry Price`: `avg_price`
- `Current Price`: the selected long adverse price for the current bar
- `MVS`: `position_size * current_price`
- `Open Profit`: `(current_price - avg_price) * position_size`
- `Equity`: `equity_value(current_price)`, which is equivalent to current cash
  plus current market value in this runtime and already reflects realized
  profit and supported commission debits
- `Margin Ratio`: `margin_long.value_percent / 100`
- `Margin`: same value exposed by `strategy.opentrades.capital_held` at
  `current_price`

M5 should trigger a margin call only when:

- `position_size > 0`;
- `margin_long.is_active()`;
- `margin_ratio > 0`;
- `current_price` is finite and positive;
- `Available Funds < 0`.

## Price Basis And Timing

For the first long-only historical subset:

- The liquidation check uses `bar.low` as the adverse long `Current Price`.
- The liquidation fill price is the same `bar.low`.
- Configured order slippage is not applied to margin-call fills in this slice;
  the official margin algorithm uses `Current Price`, and no separate slippage
  rule is documented for margin-call liquidation in the referenced Pine manual.
- The check runs after pending entry fills and before script statements on the
  same historical bar. This means script-visible `strategy.position_size`,
  `strategy.opentrades`, `strategy.equity`, and
  `strategy.opentrades.capital_held` can observe the forced reduction on the
  bar where the margin call occurs.
- If an entry fills at the bar open and the same bar's low breaches margin, M5
  may liquidate on that same bar.

Realtime margin-call timing is out of scope for M5; keep realtime behavior
unchanged until a separate realtime margin slice defines tick-by-tick behavior.

## Public Output Representation

Use the existing strategy output schema only:

- append one `StrategyOrderEvent` for the forced liquidation;
- append one `StrategyTrade` for the closed quantity;
- append one `StrategyPositionSnapshot` reflecting the remaining position;
- update the existing equity snapshots through the normal end-of-bar
  `record_equity` path;
- do not add pending-order, liquidation-price, margin-call, or broker-event
  top-level fields.

The broker-owned liquidation event should use:

- public order id and internal closed-trade `exit_id`: `Margin Call`. The
  current public trade JSON does not serialize `exit_id`, so this remains
  script-visible through supported `strategy.closedtrades.exit_id()` rather
  than a new public JSON field;
- direction in the order event: `strategy.short`, because the event reduces a
  long position;
- quantity: the positive absolute liquidated quantity;
- price: the selected `Current Price`.

For a partial liquidation:

- reduce `position_size` by the liquidated quantity;
- keep `avg_price` unchanged for the remaining long position;
- allocate the existing open entry commission proportionally to the closed
  quantity, matching existing partial-exit accounting;
- apply supported exit commission modes to the forced close, because public
  closed-trade commission fields treat the liquidation as a closed trade;
- keep the existing entry id and entry timestamps for the remaining open trade;
- recompute open-trade extremes for the remaining position using existing
  open-trade state.

For a full liquidation:

- close the position;
- clear the current entry id, entry timestamps, open entry commission, and
  open-trade extremes;
- clear pending exits for that entry id.

For partial liquidation with pending exits, M5 should conservatively clear
pending exits for the affected entry id. The current reservation ledger has no
officially verified post-liquidation reservation behavior, and clearing avoids
over-reserving against the reduced position without expanding public output.
This interaction should be fixture-checked before widening claims.

## Rounding And Truncation

TradingView truncates the cover amount to the same decimal precision as the
minimum position size for the current symbol. The current runtime has no symbol
minimum-position-size contract, so M5 must not claim full symbol-precision
parity.

For M5:

- use whole-unit `trunc()` toward zero for `Loss / Current Price`;
- convert the resulting negative long cover amount into a positive liquidation
  quantity with `abs(cover_amount * 4)`;
- clamp liquidation quantity to the current `position_size`;
- do not emit a liquidation event when the clamped quantity is not finite or is
  `<= 0`;
- document this as a temporary whole-unit truncation subset.

Future symbol precision support can replace the whole-unit truncation helper
without changing the public strategy output schema.

## M5 Fixture Shape

The first implementation fixture avoids pending exits and covers:

- an explicit active `margin_long` strategy;
- one accepted over-leveraged long entry that later breaches margin;
- one partial margin call using `bar.low`;
- script-visible plots for `strategy.position_size`,
  `strategy.opentrades.capital_held`, and `strategy.closedtrades`;
- CLI snapshot plus Python and WASM parity over the existing public strategy
  shape.

M5 must stop if the official behavior requires short exposure, pyramiding,
per-entry ledgers, a public liquidation-price field, or a public event shape
that the current strategy schema cannot represent.

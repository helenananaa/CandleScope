# Strategy Internal Margin Account Model Plan

Status: closed for the long-only margin account subset through Slice M5.

This plan defines the margin/account-model direction after Strategy Internal
Stage 7 Slice 35. It exists because the remaining `capital_held` and margin
work is not a small reporting-variable patch. Pine's official strategy broker
emulator ties margin settings to order affordability, held capital, equity,
available funds, margin calls, and forced liquidation.

## Official Semantics To Preserve

Primary official references:

- TradingView Pine Script strategies, Margin section:
  https://www.tradingview.com/pine-script-docs/concepts/strategies/
- TradingView Pine Script reference, `strategy()` and
  `strategy.opentrades.capital_held`:
  https://www.tradingview.com/pine-script-reference/v6/
- TradingView Pine v6 migration guide, default margin percentage:
  https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-6/

Compatibility facts that must guide implementation:

- `margin_long` and `margin_short` are `strategy()` declaration parameters that
  express margin percentages for long and short positions.
- Pine v5 default margin is `0`; Pine v6 default margin is `100`.
- A margin percent of `100` means a trade must be fully covered by simulated
  account funds. A smaller nonzero percent allows leverage.
- `strategy.opentrades.capital_held` is a read-only `series float` variable,
  not a per-trade field function. It returns `na` when the strategy does not
  simulate funding trades with nonzero margin settings.
- A margin-backed strategy must calculate margin using market value and the
  margin ratio, then compare that value against equity to determine available
  funds.
- If available funds cannot cover losses, the broker emulator performs a
  margin call and liquidates part or all of the open position. TradingView's
  documented algorithm liquidates four times the amount required to cover the
  loss.

## Current Runtime Boundary

Current supported strategy model:

- one net long position;
- no shorts, reversals, pyramiding, or per-entry open-trade ledger;
- supported entry, close, cancel, and selected `strategy.exit` subsets;
- cash, market value, equity snapshots, and realized net profit;
- fixed, percent-of-equity, supported commission modes, slippage, and limit
  verification;
- explicit margin settings in `pine_ir::StrategySettings`;
- `strategy.opentrades.capital_held` returns `na` in the no-margin subset and
  current long margin requirement in the explicit active `margin_long` subset;
- supported long entry fills check affordability at the actual fill price when
  explicit active `margin_long` is configured;
- supported long-only forced liquidation uses `bar.low`, the documented
  available-funds algorithm, and temporary whole-unit truncation.

Current public output boundary:

- CLI JSON, Python dictionaries, and WASM JSON expose the existing
  `strategy.orders`, `strategy.trades`, `strategy.position`,
  `strategy.equity`, and `strategy.diagnostics` shape.
- Stage 7 reporting slices have intentionally avoided adding public open-trade
  records.

## Non-Goals

Do not implement these inside the first margin/account slice:

- shorts or automatic reversal;
- pyramiding or separate open-trade ledgers;
- public JSON schema expansion;
- broker UI integration or live broker behavior;
- `strategy.margin_liquidation_price`;
- `strategy.risk.*`;
- currency conversion;
- symbol-specific minimum contract/share precision unless the slice explicitly
  designs rounding.

## Design Decisions Before Runtime Work

Before code changes, the project must choose and document these decisions:

- Version mode: whether this project interprets the existing fixtures as v5
  behavior, v6 behavior, or a project-wide compatibility profile. This matters
  because v5 default margin is `0`, while v6 default margin is `100`.
- Margin setting representation: add a dedicated IR setting that records both
  the numeric value and whether the parameter was explicitly present, because
  `capital_held` depends on whether funding simulation is active.
- Script-only versus public-output behavior: first implementation should keep
  margin effects script-visible and preserve the current public strategy JSON
  shape unless a later schema plan explicitly expands it.
- Order-affordability timing: define whether margin constraints are checked at
  order placement, at fill time, or both for each currently supported entry
  kind.
- Liquidation representation: decide whether a margin call emits a public
  order/trade in the existing strategy arrays, and what id/direction fields it
  uses, before implementing forced liquidation.
- Rounding: defer symbol precision rounding unless and until the margin-call
  slice needs it. Do not silently approximate TradingView's truncation rule
  without a fixture-backed contract.

## Intended Internal Model

Add a small internal account model instead of spreading margin math across
strategy built-ins:

```text
StrategySettings
  initial_capital
  default_qty
  commission
  slippage_ticks
  backtest_fill_limit_ticks
  margin_long
  margin_short

StrategyMarginSetting
  value_percent
  explicit

BrokerState
  account settings
  cash
  position_size
  avg_price
  realized_profit/trades
  margin state helpers
```

Suggested helper responsibilities:

- `margin_ratio_for_direction(direction)` returns `None` for no funding
  simulation and `Some(percent / 100)` for active margin.
- `open_position_market_value(price)` returns absolute market value for the
  open position.
- `open_position_money_spent()` returns `abs(position_size) * avg_price`.
- `margin_required(price)` returns market value times active margin ratio.
- `available_funds(price)` returns `equity(price) - margin_required(price)`.
- `capital_held(price)` returns `na` without active margin and the current
  margin requirement with active margin.
- `margin_call_quantity(price)` implements the official liquidation algorithm
  only after the fill/liquidation representation is designed.

## Slice Sequence

### Slice M0: Design Gate Closeout

Document the model and update status docs. No code behavior changes.

Acceptance:

- this document exists;
- execution plan and Stage 7 audit point to this design gate;
- no conformance support is widened.

### Slice M1: Declaration And IR Boundary

Closed on 2026-06-03.

Add `margin_long` and `margin_short` parsing to `strategy(...)` without enabling
runtime margin behavior.

Contract:

- accepts finite non-negative const numeric values;
- stores explicit presence separately from numeric value;
- keeps current no-margin runtime behavior until the broker slice uses the
  settings;
- keeps `strategy.opentrades.capital_held` returning `na` when neither margin
  parameter is explicitly nonzero under the active compatibility profile.

Tests:

- sema fixture accepting `strategy(..., margin_long=N, margin_short=N)`;
- sema fixture rejecting non-finite or negative values;
- unsupported declaration fixture updated only for properties that remain
  unsupported.

Stop condition:

- stop if version-default behavior cannot be decided from project policy.

### Slice M2: Long-Only Capital Held

Closed on 2026-06-03.

Implement script-visible `strategy.opentrades.capital_held` for the current
one-net-long model when active long margin is configured.

Contract:

- no public JSON schema expansion;
- flat position returns `0.0` when active margin simulation exists;
- open long position returns current market value times `margin_long / 100`;
- no order rejection or forced liquidation yet;
- no short handling.

Tests:

- runtime fixture plotting `capital_held` before entry, while long, and after
  close;
- Python and WASM plot parity;
- conformance row updated to describe long-only active-margin capital held.

Stop condition:

- stop if TradingView evidence shows `capital_held` uses a different price
  basis than current market value for open long positions.

### Slice M3: Long Entry Affordability

Closed on 2026-06-03.

Apply active long margin constraints to supported long entry fills.

Contract:

- a supported long fill is accepted only when simulated equity can cover the
  required margin at the fill price;
- rejected fills should report a strategy diagnostic and leave position, cash,
  orders, trades, and pending exits unchanged except for explicitly documented
  pending-order cleanup;
- market, limit, stop, and stop-limit entries must share the same affordability
  helper at their actual fill price.

Tests:

- accepted fully covered long entry;
- rejected over-leveraged long entry;
- limit/stop pending entries that become unaffordable at fill time;
- host parity verifies public shape remains unchanged.

Stop condition:

- stop if public output must represent rejected orders differently.

### Slice M4: Long-Only Margin Call Design

Closed on 2026-06-03. See
`docs/STRATEGY_INTERNAL_MARGIN_CALL_DESIGN.md`.

Before implementing liquidation, write a narrow liquidation design note with
exact public output and rounding decisions.

Acceptance:

- official algorithm mapped onto the current long-only broker fields;
- liquidation price basis and historical-bar timing documented;
- output representation documented;
- rounding/truncation rule either implemented from a clear symbol precision
  contract or explicitly deferred.

### Slice M5: Long-Only Forced Liquidation

Closed on 2026-06-03.

Implement margin-call liquidation only after M4 closes.

Contract:

- current one-net-long position only;
- official available-funds and four-times-cover algorithm;
- public order/trade representation follows M4;
- partial liquidation updates cash, position, average price, open-trade
  commission allocation, counts, equity snapshots, run-up/drawdown, and
  `capital_held`.

Stop condition:

- stop if liquidation interacts with unsupported shorts, pyramiding, or
  per-entry ledgers in a way that cannot be represented by the current broker.

## Fixture Plan

Minimum fixtures after runtime support begins:

- `supported_strategy_margin_declaration.pine`
- `unsupported_strategy_margin_declaration.pine`
- `strategy_margin_capital_held_long.pine`
- `strategy_margin_entry_affordability_long.pine`
- `strategy_margin_call_long.pine`

Host parity:

- CLI snapshot for each runtime fixture;
- Python plot parity for script-visible values;
- WASM JSON parity for the same fixture;
- no new public strategy object fields unless a later schema plan says so.

## Closeout Criteria

A margin/account slice is closed only when:

- official semantics used by the slice are cited in docs;
- `tests/fixtures/conformance.tsv` names the exact supported subset;
- docs make no broader margin, short, pyramiding, or liquidation claim;
- CLI, Python, and WASM behavior are covered if runtime behavior changes;
- `scripts/verify.sh` passes before commit.

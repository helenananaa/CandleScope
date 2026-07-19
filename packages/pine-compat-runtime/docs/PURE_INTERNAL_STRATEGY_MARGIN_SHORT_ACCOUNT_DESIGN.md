# Pure Internal Strategy Margin Short And Account Design

Status: design gate closed. This document does not enable new runtime behavior.

This note closes the pure-internal design gate for the margin/account work that
remains after the existing long-only margin slices:

- `margin_short` runtime behavior;
- `strategy.margin_liquidation_price`;
- symbol precision and liquidation rounding;
- currency conversion and richer account constraints.

It extends, but does not replace,
`docs/STRATEGY_INTERNAL_MARGIN_ACCOUNT_MODEL_PLAN.md` and
`docs/STRATEGY_INTERNAL_MARGIN_CALL_DESIGN.md`.

## Current Boundary

The current interpreter supports a deliberately narrow account model:

- `strategy(..., margin_long=N, margin_short=N)` accepts finite non-negative
  const numeric values and stores explicit presence in IR;
- explicit active `margin_long` drives long-only
  `strategy.opentrades.capital_held`;
- supported long fills are rejected when equity cannot cover required long
  margin at the actual fill price;
- long-only forced liquidation uses `bar.low` and temporary whole-unit
  truncation;
- no public strategy output schema exposes margin calls, liquidation prices, or
  account ledgers beyond the existing orders/trades/position/equity fields.

`margin_short` is not a runtime margin model yet. Its parsed setting must remain
inert until short exposure and short account semantics are implemented together.

## Design Principles

Future account work must keep these invariants:

- direction-specific margin settings select the active margin ratio:
  `margin_long` for positive exposure and `margin_short` for negative exposure;
- account math must use absolute market value for margin requirement while
  preserving direction-specific open profit:
  long profit is `(price - avg_price) * abs(size)`, short profit is
  `(avg_price - price) * abs(size)`;
- affordability checks happen at the actual fill price for every supported fill
  path that can increase exposure;
- liquidation checks use the adverse price for the open direction:
  `bar.low` for long exposure and `bar.high` for short exposure in the first
  historical subset;
- forced liquidation reduces exposure with the opposite public order direction
  and must update the same script-visible state observed by supported strategy
  variables;
- public JSON, Python, and WASM shapes stay unchanged until a separate schema
  design intentionally exposes account or pending-order ledgers.

## Short Margin Sequence

Do not implement `margin_short` in isolation. It depends on the short/reversal
design gate because a short margin call cannot be fixture-backed while the
broker has no supported negative exposure.

The first positive short margin slice should:

1. enable only the already-designed positive short-entry subset;
2. add `margin_ratio_for_direction(direction)` and
   `margin_required_for_position(price)` helpers before wiring call sites;
3. make `strategy.opentrades.capital_held` return short market value times
   `margin_short / 100` for supported open short exposure;
4. reject unaffordable short exposure increases at fill time;
5. keep no-margin and long-margin fixtures unchanged.

It must stop before mixed long/short ledgers, multi-entry allocation, or public
schema expansion unless that slice explicitly designs those contracts.

## Short Liquidation

Short liquidation should mirror the existing long-only margin-call model, with
direction-specific terms:

- current price uses the adverse short price (`bar.high`) for the first
  historical subset;
- market value is `abs(position_size) * current_price`;
- open profit is `(avg_price - current_price) * abs(position_size)`;
- margin required is market value times `margin_short / 100`;
- available funds are `equity(current_price) - margin_required`;
- the cover quantity uses the same documented four-times-cover algorithm after
  adapting sign and direction;
- the emitted public order direction is `strategy.long` because it reduces a
  short position.

Pending exits and reservations for the affected short entry id should follow
the same conservative rule as the current long margin call: clear affected
reservations until a broader reservation ledger is designed.

## Liquidation Price Variable

`strategy.margin_liquidation_price` must not be exposed as a constant placeholder.
It should become script-visible only after the account model can compute the
price at which available funds cross zero for the supported open exposure.

Initial behavior should be:

- `na` when the strategy is flat or no active margin setting applies to the
  current exposure;
- a finite series float for a supported single-direction open position when the
  crossing price can be solved from current equity, position size, average
  price, and the active margin ratio;
- updated after fills, exits, and forced liquidations on the same timing boundary
  used by other supported strategy state variables;
- unsupported for mixed exposure, unresolved currency conversion, invalid
  prices, or account states that the current broker cannot represent.

The first implementation should add semantic fixture coverage for read-only
variable behavior and runtime fixture coverage for long-only values before
claiming short parity.

## Precision, Rounding, And Currency

The current long liquidation subset intentionally uses whole-unit truncation.
Before claiming symbol-precision parity, add a broker precision profile that
captures at least:

- minimum position size;
- position quantity precision;
- price tick size;
- monetary rounding rules for commissions, margin, and realized profit.

Liquidation rounding must then truncate cover quantity to the configured minimum
position increment instead of always truncating to whole units.

Currency conversion remains out of scope for margin runtime widening until the
interpreter has a symbol/account currency contract. Before enabling it, decide:

- account currency and symbol currency representation in strategy settings;
- conversion source and bar timing;
- how unavailable conversion data is diagnosed;
- whether conversion affects only order/account math or also public reports.

Until those decisions are implemented, cash default quantity, percent-of-equity
default quantity, margin checks, and liquidation math all stay in the current
single-currency subset.

## Acceptance For Future Runtime Work

A runtime slice that uses this design gate should include:

- sema fixtures for any newly exposed script-visible variable or declaration
  argument behavior;
- runtime fixtures for long and short account math at the same observation
  points;
- CLI golden snapshot coverage and Python/WASM parity when public strategy
  outputs can change through existing fields;
- conformance and matrix updates only after behavior is fixture-backed.

If implementation requires public pending-order ledgers, public liquidation
events outside the existing order/trade arrays, or mixed-position accounting,
stop and write a separate schema/account-ledger design first.

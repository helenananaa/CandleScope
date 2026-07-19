# Strategy Internal Stage 12 Declaration Properties Plan

Status: closed on 2026-06-05. See
`docs/STRATEGY_INTERNAL_STAGE12_DECLARATION_PROPERTIES_AUDIT.md`.

## Background

Stage 11 closed the current partial `strategy.close()` subset. Before widening
another broker operation, the remaining strategy gaps need a clean declaration
property boundary. The live conformance matrix already documents a non-trivial
`strategy()` subset:

- positive const `initial_capital`;
- `strategy.fixed`, `strategy.cash`, and `strategy.percent_of_equity` default
  quantities;
- `strategy.commission.cash_per_contract`,
  `strategy.commission.cash_per_order`, and `strategy.commission.percent`;
- non-negative fixed-tick `slippage`;
- non-negative fixed-tick `backtest_fill_limits_assumption`;
- finite non-negative `margin_long` and `margin_short` declaration parsing;
- active `margin_long` behavior for the current long-only capital-held,
  affordability, and forced-liquidation subset.

The old gap audit still described this area as mostly unsupported and pointed at
already-closed close/exit work. Stage 12 starts by making the next declaration
property decision explicit instead of accepting a low-value keyword alias.

## Goal

Choose the next declaration-property expansion only after its semantic boundary,
broker effect, conformance wording, and public output contract are clear.

## Non-Goals

- No runtime widening in this design slice.
- No acceptance of `pyramiding`, `calc_on_order_fills`,
  `calc_on_every_tick`, `process_orders_on_close`, `currency`,
  `close_entries_rule`, `risk_free_rate`, `use_bar_magnifier`,
  `fill_orders_on_standard_ohlc`, or strategy alert/order-fill settings.
- No short exposure, reversal, multi-entry ledger, OCA, or public order-event
  schema expansion.

## Candidate Slices

### Slice 1: Boundary Lock

Status: closed on 2026-06-05.

Refresh or add semantic fixtures proving the unsupported declaration properties
remain rejected with stable diagnostics. This should cover the properties above
without duplicating already-supported declaration forms.

Close criteria:

- Unsupported property fixture coverage is explicit.
- `tests/fixtures/conformance.tsv` keeps the supported declaration subset narrow
  and registers the declaration-property rejection fixtures under the unsupported
  `strategy.*` row.
- CLI conformance and matrix snapshots remain unchanged except for intentional
  fixture registration.

Closed evidence:

- `tests/fixtures/sema/unsupported_strategy_declaration_properties.pine` now
  covers only unsupported declaration properties, leaving supported slippage,
  limit-verification, commission, and margin declarations to their dedicated
  fixtures.
- `crates/pine-sema/tests/fixtures.rs` checks that each target unsupported
  property name appears in declaration diagnostics.

### Slice 2: Property Selection Review

Status: closed on 2026-06-05. Selected
`default_qty_type=strategy.cash` for the first runtime implementation slice.

Pick exactly one declaration property only if it has a defensible current-broker
semantics. The first runtime slice should prefer a property that changes real
behavior and can be fixture-backed without opening multi-entry, realtime, or
short-position semantics.

Current assessment:

- `pyramiding=0/1` as an accepted no-op is low value because the broker still has
  one net long position and ignores repeated long entries.
- `process_orders_on_close` changes order timing and should wait for a fill-timing
  design.
- `calc_on_order_fills` and `calc_on_every_tick` require recalculation/realtime
  execution semantics.
- `default_qty_type=strategy.cash` is narrow enough to implement next if the
  first slice records the current no-currency-conversion and no-precision-rounding
  boundary explicitly.
- `margin_short` runtime behavior should wait for short exposure.
- `close_entries_rule` should wait for multi-entry ledgers.

Decision:

- Implement `default_qty_type=strategy.cash` next.
- Resolve omitted supported `strategy.entry` quantities once at placement time
  as `default_qty_value / close`, using the current chart/account currency
  identity assumption.
- Preserve explicit `qty` precedence over declaration defaults.
- Keep runtime behavior unsupported when the current close is non-finite or
  non-positive by routing through the existing invalid-quantity diagnostic path.
- Keep currency conversion, symbol precision rounding, lot-step constraints,
  `currency`, `strategy.order`, short entries, and multi-entry/pyramiding out of
  scope.

Rationale:

- The existing fixed and percent-of-equity default quantity plumbing already
  resolves omitted entry quantities at placement time.
- Cash sizing changes real behavior without requiring order-on-close,
  recalculation, realtime ticks, short exposure, or multi-entry ledgers.
- It can be fixture-backed across sema, runtime, CLI golden, Python, and WASM
  using the current long-only entry subset and unchanged public JSON shape.

### Slice 3: Runtime Implementation

Status: closed on 2026-06-05.

Implement only `default_qty_type=strategy.cash`.

Close criteria:

- `strategy.cash` is registered as a supported strategy default quantity type.
- Positive const `default_qty_value` supplies a cash amount for omitted supported
  `strategy.entry` quantities.
- Runtime fixtures prove cash sizing for market entries and one pending-entry
  form, plus explicit `qty` precedence.
- Conformance, matrix snapshot, execution semantics, builtin signatures, release
  notes, CLI/Python/WASM parity, and `scripts/verify.sh` all pass.

Closed evidence:

- `strategy.cash` is registered as a string constant and accepted by the
  `strategy()` declaration analyzer.
- `StrategyDefaultQuantity::Cash` resolves omitted supported entry quantities as
  cash divided by current close, preserving explicit `qty` precedence.
- Runtime fixtures cover cash default market entries, cash default limit entries,
  and explicit-`qty` override behavior with unchanged public strategy JSON shape.
- CLI golden snapshots, Python binding tests, WASM CSV-to-JSON tests, the
  conformance matrix, and compatibility docs are synchronized.

## Compatibility Contract

The supported strategy declaration subset is the one recorded in
`tests/fixtures/conformance.tsv`. Unsupported declaration properties must fail
before runtime execution, and public strategy JSON must not grow
declaration-setting fields.

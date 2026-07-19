# Strategy Internal Stage 12 Declaration Properties Audit

Status: closed on 2026-06-05 for the documented declaration-property boundary
and `strategy.cash` default quantity subset.

Stage 12 refreshed the post-Stage-11 declaration-property gap boundary, locked
unsupported `strategy()` declaration properties behind fixture-backed semantic
diagnostics, selected a low-blast-radius next property, and implemented
`default_qty_type=strategy.cash` for the current long-only entry subset. Public
CLI, Python, and WASM strategy JSON shape remains unchanged.

## Completed Surface

- Unsupported declaration properties remain rejected before runtime execution:
  `calc_on_order_fills`, `calc_on_every_tick`, `process_orders_on_close`,
  `currency`, `close_entries_rule`, `risk_free_rate`, `use_bar_magnifier`, and
  `fill_orders_on_standard_ohlc`.
- `strategy.cash` is now a supported string constant and accepted
  `default_qty_type`.
- `strategy(default_qty_type=strategy.cash, default_qty_value=N)` accepts finite
  positive const numeric `N`.
- When a supported `strategy.entry` omits `qty`, the cash default quantity
  resolves once at placement time as `N / close`.
- Explicit `qty` still overrides declaration defaults.
- The implementation applies only under the current chart/account currency
  identity assumption. It does not introduce currency conversion, symbol
  precision rounding, lot-step constraints, short exposure, pyramiding, or public
  schema expansion.

## Repository Evidence

- `crates/pine-builtins/src/constants/strings.rs` registers `strategy.cash`.
- `crates/pine-sema/src/analyzer/strategy.rs` maps
  `default_qty_type=strategy.cash` into `StrategyDefaultQuantity::Cash` and keeps
  unsupported default quantity types rejected.
- `crates/pine-ir/src/strategy.rs` resolves `StrategyDefaultQuantity::Cash` as
  cash divided by placement close, returning no default quantity for non-finite or
  non-positive prices so the existing invalid-quantity strategy diagnostic path
  applies.
- `crates/pine-runtime/src/builtins/strategy.rs` continues to resolve omitted
  `strategy.entry` quantity through the shared `default_entry_qty` path, so fixed,
  cash, and percent-of-equity defaults share one placement-time boundary.
- `crates/pine-runtime/src/tests/strategy.rs` covers cash default market entry
  sizing and cash default limit-entry sizing at placement close.
- `tests/fixtures/sema/supported_strategy_cash_default_quantity.pine` covers the
  accepted declaration and explicit-`qty` override syntax. The existing
  `unsupported_strategy_default_quantity.pine` fixture now rejects an actually
  unsupported default quantity type.
- Runtime fixtures and golden snapshots cover the public JSON contracts:
  `strategy_cash_default_quantity.pine`,
  `strategy_cash_default_quantity_limit.pine`, and
  `strategy_cash_default_quantity_override.pine`.
- Python bindings cover the same public contract through
  `test_run_script_returns_strategy_cash_default_quantity_contract`.
- WASM tests cover the CSV-to-public-JSON contract through
  `runs_strategy_cash_default_quantity_from_csv_to_strategy_json`.
- `tests/fixtures/conformance.tsv` and `tests/snapshots/matrix.json` record cash
  default quantity support and keep the remaining strategy boundary unsupported.
- `docs/EXECUTION_SEMANTICS.md`, `docs/BUILTIN_SIGNATURES.md`,
  `docs/CONFORMANCE.md`, `docs/SEMANTIC_MODEL.md`, and
  `docs/STRATEGY_INTERNAL_GAP_AUDIT.md` describe the supported cash default
  quantity subset and the remaining precision/currency limitations.

## Verification

The closeout slice used the canonical release gate:

```text
scripts/verify.sh
```

The behavior slice also refreshed and rechecked CLI runtime golden snapshots and
the conformance matrix, then verified sema, runtime, WASM, Python, clippy,
wasm32, and structure gates through `scripts/verify.sh`.

## Still Unsupported

- `pyramiding`, `calc_on_order_fills`, `calc_on_every_tick`, and
  `process_orders_on_close`.
- `currency`, currency conversion, symbol precision rounding, lot-step
  constraints, and contract/share minimum handling.
- Runtime short margin behavior, short entries, reversals, and multi-entry
  ledgers.
- `close_entries_rule`, custom close ordering, OCA behavior, and generic
  `strategy.order()`.
- Strategy alert/order-fill settings, alert-message metadata, and public
  order-event schema expansion.

## Next Direction Boundary

Stage 12 should stop here. The declaration-property boundary is synchronized and
`strategy.cash` is fixture-backed across semantic analysis, runtime snapshots,
conformance, matrix, Python, and WASM.

The next internal strategy stage should not pick another declaration property by
default. Remaining declaration properties are tied to larger broker-model work:
fill timing, recalculation, realtime execution, short exposure, multi-entry
ledgers, currency/precision modeling, or public order-event output.

# Strategy Internal Stage 11 Partial Close Audit

Status: closed on 2026-06-05 for the documented one-net-long
`strategy.close` partial quantity subset.

Stage 11 widened market close support without changing the public CLI, Python,
or WASM strategy result schema. The implemented subset is limited to the current
long-only, one-net-position broker and a matching current entry id.

## Completed Surface

- `strategy.close(id)` keeps the existing full close behavior for the matching
  current long entry id.
- `strategy.close(id, qty=...)` closes a finite positive fixed quantity at the
  current bar close.
- `strategy.close(id, qty_percent=...)` resolves a finite positive percentage
  against the current matching position size, then closes that quantity at the
  current bar close.
- `strategy.close(id, qty=..., qty_percent=...)` uses fixed `qty`; `qty_percent`
  is ignored for quantity selection.
- Oversized fixed quantities and over-100 percentages clamp to the current
  matching position size.
- Partial closes leave the remaining long position open at the same average
  price and keep matching pending exits alive. A close that fully flattens the
  entry cancels matching pending exits.
- Invalid fixed quantities emit `E_STRATEGY_CLOSE_QTY`; invalid percent
  quantities emit `E_STRATEGY_CLOSE_QTY_PERCENT`. Both preserve existing
  position, pending exit, and trade state.
- Public output remains the existing strategy shape: `orders`, `trades`,
  `position`, `equity`, and `diagnostics`. `strategy.close` fills appear as
  closed trades and position/equity changes, not as separate close order events
  or public pending-order fields.

## Repository Evidence

- `crates/pine-builtins/src/namespaces/strategy.rs` registers `strategy.close`
  with `id`, optional `qty`, and optional `qty_percent`.
- `crates/pine-sema/src/analyzer/strategy.rs` requires partial close quantities
  to be named arguments and validates const `qty` / `qty_percent` values as
  finite and positive.
- `crates/pine-runtime/src/builtins/strategy.rs` routes `strategy.close` to full,
  fixed-quantity, or percent-quantity broker close helpers, with fixed `qty`
  taking precedence when both quantity forms are present.
- `crates/pine-runtime/src/strategy/broker/fills.rs` owns the shared close
  quantity path and the percent-to-absolute quantity resolution.
- Broker tests cover fixed quantity, percent quantity, full clamps, invalid
  quantities, pending-exit preservation for partial closes, and pending-exit
  cleanup for full closes:
  `close_long_fixed_quantity_reduces_position_and_keeps_pending_exit`,
  `close_long_fixed_quantity_clamps_full_and_cancels_pending_exit`,
  `close_long_invalid_fixed_quantity_preserves_position_and_pending_exit`,
  `close_long_percent_quantity_reduces_position_and_keeps_pending_exit`,
  `close_long_percent_quantity_clamps_full_and_cancels_pending_exit`, and
  `close_long_invalid_percent_quantity_preserves_position_and_pending_exit`.
- Runtime fixtures and golden snapshots cover the public contracts:
  `strategy_close_qty_partial.pine`,
  `strategy_close_qty_full_clamp.pine`, and
  `strategy_close_qty_percent_precedence.pine`.
- Semantic fixtures cover accepted `qty`, accepted `qty_percent`, accepted `qty`
  precedence, unsupported positional quantity-like arguments, invalid const
  quantities, unsupported close metadata, and indicator-mode rejection.
- Python bindings cover the fixed-quantity and percent/precedence runtime
  contracts through
  `test_run_script_returns_strategy_close_qty_partial_contract` and
  `test_run_script_returns_strategy_close_qty_percent_precedence_contract`.
- WASM tests cover the same public JSON shape through
  `runs_strategy_close_qty_partial_from_csv_to_trade_json` and
  `runs_strategy_close_qty_percent_precedence_from_csv_to_trade_json`.
- `tests/fixtures/conformance.tsv` and `tests/snapshots/matrix.json` name the
  supported full close, fixed-qty partial close, qty-percent partial close, and
  `qty` precedence subset while preserving the broader unsupported strategy
  boundary.

## Verification

The closeout slice used the canonical release gate:

```text
scripts/verify.sh
```

Before closeout, the behavior slices also ran targeted builtins, semantic,
runtime, broker, CLI snapshot, conformance, WASM, Python, incremental, clippy,
and structure checks.

## Still Unsupported

- Positional partial quantity arguments such as `strategy.close("L", 1)`.
- `strategy.close` comments, alert messages, alert suppression, and
  `immediately`.
- Partial `strategy.close_all()`.
- Close allocation across multiple open entries, pyramiding, shorts, reversals,
  custom close ordering, and `close_entries_rule`.
- Public close-order events, public pending-order output, close comments, alert
  payload output, or other strategy result schema expansion.
- Tick-level, bar-magnifier, or intrabar ordering behavior beyond the current
  historical bar model.

## Next Direction Boundary

Stage 11 should stop here. The partial `strategy.close` subset is now
fixture-backed across broker internals, runtime snapshots, conformance, matrix,
Python, and WASM.

The next internal strategy stage should be selected from a fresh repo-grounded
gap audit. Do not infer close metadata, partial `strategy.close_all()`,
multi-entry allocation, pyramiding, shorts, or public order-event support from
the Stage 11 implementation.

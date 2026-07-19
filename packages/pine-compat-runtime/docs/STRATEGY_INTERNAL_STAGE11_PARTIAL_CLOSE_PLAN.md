# Strategy Internal Stage 11 Partial Close Plan

Status: closed on 2026-06-05 for the documented one-net-long
`strategy.close` partial quantity subset. See
`docs/STRATEGY_INTERNAL_STAGE11_PARTIAL_CLOSE_AUDIT.md`.

Stage 11 targets the next narrow Pine strategy gap after the Stage 10
active-entry bracket closeout: `strategy.close()` partial market closes for
the current one-net-long broker model.

Primary official references reviewed on 2026-06-05:

- TradingView Pine Script strategies:
  https://www.tradingview.com/pine-script-docs/concepts/strategies/
- TradingView Pine Script language reference:
  https://www.tradingview.com/pine-script-reference/v5/

Relevant official rules:

- `strategy.close(id, comment, qty, qty_percent, alert_message, immediately,
  disable_alert)` generates a market order for open trades matching `id`;
- `qty` and `qty_percent` can close part of the matching position;
- when both `qty` and `qty_percent` are supplied, `qty` determines the order
  quantity;
- `strategy.close()` market orders are distinct from price-based
  `strategy.exit()` orders;
- `immediately`, comments, alert messages, and alert suppression are separate
  behavior surfaces from quantity selection.

## Starting Point

The current repo baseline is:

- `strategy.close(id)` closes the full current long position at the current bar
  close when `id` matches the current open entry id.
- `strategy.close_all()` closes the full current long position without an entry
  id.
- `strategy.exit()` already supports fixed `qty`, `qty_percent`, and `qty` over
  `qty_percent` precedence across supported single-trigger, bracket, and
  trailing exit shapes.
- The broker ledger already has FIFO allocation helpers that can allocate a
  requested exit quantity against the current open trade list.
- Public strategy output already represents partial fills through ordinary
  order/trade quantities and the remaining `position` object; no schema change
  is needed for the first Stage 11 subset.

## Compatibility Boundary

Stage 11 may support only this first partial-close subset:

- long-only strategy mode;
- one current net long position;
- one matching current entry id;
- `strategy.close(id, qty=...)`;
- `strategy.close(id, qty_percent=...)`;
- `strategy.close(id, qty=..., qty_percent=...)` where `qty` wins;
- market close at the current bar close using the existing close fill price and
  slippage rules;
- clamping over-sized quantities to the current matching open quantity;
- preserving remaining position average price, open-trade fields, realized
  profit, commission allocation, runup/drawdown allocation, pending-exit
  cleanup, CLI/Python/WASM strategy JSON shape, and conformance discipline.

Stage 11 must not add:

- partial `strategy.close_all()`;
- `immediately` or `process_orders_on_close` behavior;
- `comment`, `alert_message`, `disable_alert`, or strategy order-fill alert
  delivery;
- partial closes across multiple entries, pyramiding, shorts, or reversals;
- custom close ordering or `close_entries_rule`;
- public close-order events, public pending-order output, or strategy schema
  expansion.

## Design Requirement

Partial `strategy.close()` should reuse the existing broker close path where
possible, but the full-close path must be split so it can close a requested
quantity without flattening the entire position.

The internal close quantity model should mirror the already supported
`strategy.exit` quantity semantics for the current one-net-long subset:

```text
CloseQuantityArg::Full
CloseQuantityArg::Fixed(qty)
CloseQuantityArg::Percent(qty_percent)
```

Resolution for the current long-only subset:

- `Full` closes the full matching current position, preserving the existing
  `strategy.close(id)` behavior.
- `Fixed(qty)` requires a finite positive quantity and closes
  `min(qty, current_matching_quantity)`.
- `Percent(qty_percent)` requires a finite positive percentage, resolves to
  `current_matching_quantity * qty_percent / 100`, and closes no more than the
  current matching quantity.
- If both `qty` and `qty_percent` are supplied, use `Fixed(qty)`.
- Invalid quantities should record a strategy diagnostic and leave position,
  pending exits, and trade state unchanged.

Pending-exit cleanup needs a documented policy before runtime widening. The
conservative first subset should match the existing `strategy.exit` partial
behavior: a partial market close keeps the remaining long position open and
does not cancel unrelated pending exits for the same entry unless the close
fully flattens that entry. A full close keeps the existing behavior of
cancelling matching pending exits.

## Slice Plan

### Slice 0: Design Gate

Status: this document. This slice does not add runtime behavior, widen
conformance, or update matrix support claims.

Goal:

- define the Stage 11 `strategy.close` partial quantity boundary before
  changing builtin signatures, semantic validation, or broker close behavior.

Acceptance:

- current repo baseline is documented;
- supported and unsupported Stage 11 forms are explicit;
- pending-exit cleanup policy is chosen for partial versus full close;
- implementation ownership stays in builtins, semantic analysis, broker fills,
  fixtures, and host parity tests;
- no runtime fixtures, snapshots, conformance rows, or matrix claims change.

### Slice 1: Boundary Lock

Status: Closed on 2026-06-05. This slice added semantic boundary coverage only
and did not widen runtime behavior, conformance, matrix, or public output.

Goal:

- add semantic and/or runtime boundary tests proving `strategy.close` partial
  quantity forms remain unsupported before behavior routing changes.

Closed evidence:

- added semantic fixture
  `tests/fixtures/sema/unsupported_strategy_close_partial_quantity.pine`;
- added a fixture test proving positional quantity-like arguments, `qty`,
  `qty_percent`, `comment`, `alert_message`, `disable_alert`, and
  `immediately` were rejected by the Slice 1 `strategy.close` signature;
- no runtime fixtures, snapshots, conformance rows, matrix support claims,
  Python tests, or WASM tests changed.

Acceptance:

- `strategy.close("L", qty=...)`, `strategy.close("L", qty_percent=...)`, and
  `strategy.close("L", qty=..., qty_percent=...)` stay outside the supported
  runtime subset;
- unsupported `comment`, `alert_message`, `disable_alert`, and `immediately`
  variants remain rejected or outside the signature;
- no support claims widen.

### Slice 2: Fixed `qty` Partial Close

Status: Closed on 2026-06-05. This slice widens only the fixed-`qty`
`strategy.close(id, qty=...)` subset for the current one-net-long broker.
The public strategy JSON shape remains unchanged: close fills appear as closed
trades and position/equity changes, not as separate close order events.

Goal:

- support `strategy.close(id, qty=...)` for the current one-net-long broker.

Closed evidence:

- added `strategy.close` builtin signature support for named `qty` while
  keeping positional quantity-like calls, `qty_percent`, close metadata, and
  `immediately` outside the supported subset;
- split the broker close path so fixed quantities close
  `min(qty, current_position_size)`, preserve the remaining long position and
  average price, and cancel matching pending exits only when the close fully
  flattens the entry;
- added runtime fixtures
  `tests/fixtures/runtime/strategy_close_qty_partial.pine` and
  `tests/fixtures/runtime/strategy_close_qty_full_clamp.pine`;
- added semantic fixture
  `tests/fixtures/sema/supported_strategy_close_qty.pine` and updated
  `tests/fixtures/sema/unsupported_strategy_close_partial_quantity.pine`;
- added CLI golden snapshots, Python binding coverage, WASM CSV-to-JSON
  coverage, broker tests, conformance row updates, and matrix updates.

Acceptance:

- fixed quantities are finite and positive;
- over-sized fixed quantities clamp to the current matching position size;
- partial close records one closed trade for the closed quantity, leaves the
  remaining long position open at the same average price, and preserves public
  strategy JSON shape without adding a close order event;
- full-clamp fixed close keeps existing full-close pending-exit cancellation;
- semantic, broker, runtime, incremental, CLI, Python, WASM, conformance,
  matrix, docs, and release-note coverage close in the same slice.

### Slice 3: `qty_percent` Partial Close

Status: Closed on 2026-06-05. This slice widens only `qty_percent` and
`qty`-over-`qty_percent` precedence for the current one-net-long
`strategy.close` subset. Close metadata, `immediately`, partial
`strategy.close_all()`, and public strategy JSON expansion remain unsupported.

Goal:

- support `strategy.close(id, qty_percent=...)` and
  `strategy.close(id, qty=..., qty_percent=...)` with `qty` precedence.

Closed evidence:

- added `strategy.close` builtin signature support for named `qty_percent`;
- added semantic validation requiring finite positive const `qty_percent` values
  while keeping positional quantity-like calls and close metadata rejected;
- added broker/runtime support that resolves `qty_percent` against the current
  matching position size, clamps over-100 percentages through the shared close
  quantity path, and preserves state unchanged for invalid percentages;
- added runtime fixture
  `tests/fixtures/runtime/strategy_close_qty_percent_precedence.pine` covering
  percent partial close and `qty` precedence in the same public JSON contract;
- added semantic fixtures for `qty_percent` and `qty` precedence plus broker,
  CLI snapshot, Python, WASM, conformance, matrix, docs, and release-note
  coverage.

Acceptance:

- percentages are finite and positive;
- over-100 percentages clamp to the current matching position size;
- `qty` wins when both quantity forms are supplied;
- invalid percentages preserve existing position and pending state;
- semantic, broker, runtime, incremental, CLI, Python, WASM, conformance,
  matrix, docs, and release-note coverage close in the same slice.

### Slice 4: Closeout Audit

Status: Closed on 2026-06-05. This slice synchronized Stage 11 docs,
conformance, matrix, host parity, and audit evidence without widening runtime
behavior.

Goal:

- close Stage 11 with synchronized docs, conformance, matrix, host parity, and
  audit evidence.

Acceptance:

- a Stage 11 audit lists completed partial-close forms, still-unsupported
  close forms, and next direction boundaries;
- `tests/fixtures/conformance.tsv` precisely names the supported
  `strategy.close` partial subset;
- `scripts/verify.sh` passes before commit.

## Verification Plan

Each behavior slice should run:

```text
cargo fmt
cargo test -p pine-builtins strategy_close --quiet
cargo test -p pine-sema strategy_close --quiet
cargo test -p pine-runtime strategy_close --quiet
cargo test -p pine-runtime --test incremental --quiet
cargo test -p pine-cli runtime_outputs_match_golden_snapshots --quiet
cargo test -p pine-cli matrix_output_matches_golden_snapshot --quiet
cargo test -p pine-cli conformance --quiet
cargo test -p pine-wasm strategy --quiet
python3 -m pytest python/tests -q
python3 scripts/check_structure.py
```

Before final closeout, run:

```text
scripts/verify.sh
```

# Strategy Internal Stage 9 Entry-Relative Exit Audit

Status: closed on 2026-06-04 for the documented active pending-entry
single-trigger subset.

Stage 9 widened same-calculation `strategy.exit` attachment for matching active
pending long entries without changing the public CLI, Python, or WASM strategy
result schema. The implemented subset is limited to single-trigger
entry-relative exits that can resolve their price or activation from the actual
entry fill price after the pending entry fills.

## Completed Surface

- Same-calculation `strategy.exit(..., profit=...)` can target a matching active
  pending long entry and resolves its limit from the eventual fill price.
- Same-calculation `strategy.exit(..., loss=...)` can target a matching active
  pending long entry and resolves its stop from the eventual fill price.
- Same-calculation
  `strategy.exit(..., trail_points=..., trail_offset=...)` can target a
  matching active pending long entry and resolves trailing activation from the
  eventual fill price.
- Existing `qty` and `qty_percent` validation resolve against the matching
  pending entry quantity before the relative trigger resolves.
- Existing activation-bar and later-bar fill behavior is preserved after the
  deferred exit resolves into the normal pending-exit path.
- Public `orders`, `trades`, `position`, `equity`, and `diagnostics` output
  fields remain unchanged.

## Repository Evidence

- `BrokerState` stores deferred relative exit intent in the pending exit book
  and resolves `profit`, `loss`, and `trail_points + trail_offset` after a
  matching pending entry fills.
- `crates/pine-runtime/src/builtins/strategy.rs` keeps invalid mixed trigger
  combinations and active-entry relative bracket combinations out of the
  supported runtime path.
- Runtime fixtures cover one representative host-stable public contract for
  `profit`, `loss`, and `trail_points + trail_offset` active-entry attachment.
- `tests/fixtures/conformance.tsv` lists the supported active-entry
  single-trigger subset and keeps broader unsupported strategy behavior under
  `strategy.*`.
- `cargo run -q -p pine-cli -- matrix` reports the updated fixture-backed
  `strategy.exit` partial subset and keeps generic strategy order behavior
  unsupported.

## Verification

The closeout slice used the canonical release gate:

```text
scripts/verify.sh
```

Before the closeout, each behavior slice also ran targeted runtime, CLI,
Python, WASM, conformance, matrix, clippy, and structure checks.

## Still Unsupported

- Same-calculation active-entry relative bracket forms, including `stop +
  profit`, `loss + limit`, and `loss + profit` against an active pending entry.
- Missing-entry future binding for exits whose `from_entry` does not match an
  active pending entry or current open position.
- Short entries, reversals, pyramiding, multiple open trades, and generic
  `strategy.order()`.
- Public pending-order output or public schema expansion.
- `trail_price + trail_points` precedence changes beyond the current supported
  trailing subset.

## Next Direction Boundary

Stage 9 should stop here. Active-entry relative bracket parity is official Pine
behavior, but it needs its own design slice because it combines deferred
relative legs with existing bracket precedence, reservation, and quantity
rules.

Do not infer bracket support from the Stage 9 single-trigger implementation.

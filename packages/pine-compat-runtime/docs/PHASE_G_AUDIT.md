# Phase G Audit: Strategy Runtime

Status: closed for the first fixture-backed strategy runtime subset.

Phase G delivered a separate historical strategy mode with a narrow long-only
broker emulator and synchronized public strategy output. The compatibility
claim is intentionally partial and tied to `tests/fixtures/conformance.tsv`,
runtime snapshots, semantic fixtures, and host binding tests.

## Completed Slices

- Slice 0 locked unsupported diagnostics for the reserved strategy surface.
- Slice 1 accepted top-level `strategy(...)` declarations and added HIR script
  mode metadata without accepting order functions.
- Slice 2 added the strategy-mode public result scaffold with `orders`,
  `trades`, `position`, `equity`, and `diagnostics` arrays across CLI JSON,
  Python dictionaries, and WASM JSON.
- Slice 3 added `strategy.entry(id, strategy.long, qty=...)` for one
  current-close long market entry with no pyramiding.
- Slice 4 added `strategy.close(id)` for full close of the matching long entry
  and deterministic closed-trade output.
- Slice 5 added positive const numeric `initial_capital` and per-bar
  `cash`, `marketValue`, `equity`, and `netProfit` snapshots.

## Supported Surface

The source of truth is `tests/fixtures/conformance.tsv`.

- `strategy` is partial. Supported declaration parameters are `title`,
  `shorttitle`, `overlay`, `max_bars_back`, and positive const numeric
  `initial_capital`.
- `strategy.entry` is partial. The supported form opens one long market
  position using `strategy.long`, positive numeric `qty`, and current-bar-close
  fill. Repeated entries while a position is open are ignored.
- `strategy.close` is partial. The supported form closes the full matching long
  entry id at the current bar close. Missing, mismatched, or repeated closes
  are no-op events.
- Strategy equity is partial. Historical strategy runs append one equity
  snapshot per bar with `barIndex`, `cash`, `marketValue`, `equity`, and
  `netProfit`; open long positions are marked to the current bar close.
- Indicator-mode outputs do not include the top-level `strategy` key.

## Public Output Contract

Strategy-mode runtime output keeps runtime `schemaVersion: 3` and adds a
top-level `strategy` object:

```text
strategy: {
  orders: [],
  trades: [],
  position: [],
  equity: [],
  diagnostics: []
}
```

The first supported item shapes are:

- Order: `id`, `barIndex`, `time`, `direction`, `qty`, `price`
- Trade: `id`, `entryBarIndex`, `exitBarIndex`, `entryTime`, `exitTime`,
  `entryPrice`, `exitPrice`, `qty`, `profit`
- Position: `barIndex`, `size`, `avgPrice`
- Equity: `barIndex`, `cash`, `marketValue`, `equity`, `netProfit`
- Diagnostic: `code`, `message`

CLI and WASM share `public_runtime_result_json`; Python maps the same strategy
result into native dictionaries. Tests cover the empty strategy result, entry,
close, and equity snapshots on public host surfaces.

## Fixture Evidence

Compatibility matrix rows:

- `strategy`: `partial`
- `strategy.entry`: `partial`
- `strategy.close`: `partial`
- `strategy equity`: `partial`
- `strategy.*`: `unsupported`

Runtime fixtures and snapshots:

- `tests/fixtures/runtime/strategy_no_order.pine`
- `tests/fixtures/runtime/strategy_entry.pine`
- `tests/fixtures/runtime/strategy_close.pine`
- `tests/fixtures/runtime/strategy_equity.pine`
- `tests/snapshots/runtime_strategy_empty.json`
- `tests/snapshots/runtime_strategy_entry.json`
- `tests/snapshots/runtime_strategy_close.json`
- `tests/snapshots/runtime_strategy_equity.json`

Semantic fixtures:

- `tests/fixtures/sema/supported_strategy_declaration.pine`
- `tests/fixtures/sema/supported_strategy_initial_capital.pine`
- `tests/fixtures/sema/supported_strategy_entry.pine`
- `tests/fixtures/sema/supported_strategy_close.pine`
- `tests/fixtures/sema/unsupported_strategy_initial_capital.pine`
- `tests/fixtures/sema/unsupported_strategy_duplicate_declaration.pine`
- `tests/fixtures/sema/unsupported_strategy_local_declaration.pine`
- `tests/fixtures/sema/unsupported_strategy_entry_indicator.pine`
- `tests/fixtures/sema/unsupported_strategy_entry_short.pine`
- `tests/fixtures/sema/unsupported_strategy_entry_stop_limit.pine`
- `tests/fixtures/sema/unsupported_strategy_entry_qty.pine`
- `tests/fixtures/sema/unsupported_strategy_close_indicator.pine`
- `tests/fixtures/sema/unsupported_strategy.pine`
- `tests/fixtures/sema/unsupported_strategy_orders.pine`

`crates/pine-runtime/tests/incremental.rs` runs every runtime fixture through
full historical and incremental append execution, so the strategy runtime
fixtures also participate in full-vs-append equivalence checks.

## Verification

Slice-level verification included:

```text
cargo fmt --check
cargo test -p pine-builtins strategy -- --nocapture
cargo test -p pine-sema strategy -- --nocapture
cargo test -p pine-runtime strategy -- --nocapture
cargo test -p pine-cli golden_snapshot -- --nocapture
cargo test -p pine-wasm strategy -- --nocapture
cargo test -p pine-python strategy -- --nocapture
cargo run -q -p pine-cli -- matrix | rg "strategy|initial_capital|equity"
cargo test --workspace
git diff --check
```

The closeout workspace passed:

```text
scripts/verify.sh
```

That gate includes `cargo fmt --check`,
`cargo clippy --workspace --all-targets -- -D warnings`,
`cargo test --workspace`, `python3 scripts/check_structure.py`,
`cargo check -p pine-wasm --target wasm32-unknown-unknown`,
`maturin build --manifest-path crates/pine-python/Cargo.toml --out dist`,
wheel reinstall through `python3 -m pip install --force-reinstall dist/*.whl`,
and `python3 -m pytest python/tests`.

## Maintenance Tails

- Short entries, reversals, and short exposure remain unsupported.
- `strategy.exit`, `strategy.order`, stop/limit orders, partial exits, and
  order modification remain unsupported.
- Pyramiding and multiple simultaneous entries remain unsupported.
- Commission, slippage, margin, currency conversion, and percent-of-equity
  sizing remain unsupported.
- Strategy reporting variables and helpers such as position size, average
  price, net profit, open trades, and closed trades remain unsupported.
- Strategy alerts and alert placeholders remain unsupported.
- Realtime strategy execution and forming-bar broker rollback remain
  unsupported.
- Host-specific broker APIs or chart UI behavior remain outside the public
  runtime contract.

## Structure Check

Strategy-specific runtime state is owned by `crates/pine-runtime/src/strategy`.
Public strategy result structs are in
`crates/pine-runtime/src/output/strategy.rs`, and host bindings map those
shared structs without duplicating broker logic.

The closeout structure guard passed. `crates/pine-sema/src/analyzer/calls.rs`
is above the review threshold but below the hard guardrail; future strategy
semantic expansion should move declaration and order validation into a
strategy-owned analyzer module before adding more argument families.

## Closeout Checklist

- Indicator and strategy modes are separated in HIR and runtime output.
- Public strategy output is synchronized across CLI, Python, and WASM.
- Long entry, full close, realized trade, position, and equity behavior are
  deterministic and fixture-backed.
- Conformance rows remain narrow; `strategy.*` stays unsupported.
- Unsupported order types, broker settings, strategy variables, strategy
  alerts, and realtime broker behavior are explicit maintenance tails.
- Runtime snapshots and matrix snapshots catch accidental compatibility
  widening.
- `scripts/verify.sh` passes on the closeout workspace.

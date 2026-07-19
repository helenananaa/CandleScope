# Strategy Internal Stage 8 Broker Expansion Audit

Status: closed on 2026-06-04 for the behavior-preserving internal broker
expansion skeleton.

Stage 8 did not widen Pine strategy compatibility. It moved the current
fixture-backed one-net-long strategy broker toward explicit internal order,
trade, allocation, and fill-routing components while keeping public CLI,
Python, and WASM strategy output on the existing `StrategyResult` shape.

## Completed Surface

- `OrderBook` owns the current pending-entry and pending-exit books behind one
  broker facade.
- `TradeLedger` records current long open-trade metadata and internal FIFO
  allocation helpers.
- Current supported exit fills consume allocation metadata before recording
  public closed trades.
- Current supported entry fills build one `OpenTrade` metadata object and use
  it for both legacy one-position state and the internal ledger.
- Public order events, public position snapshots, public closed trades, full
  flat-state cleanup, and open-long legacy state setup now route through
  broker-internal helpers.
- Existing `orders`, `trades`, `position`, `equity`, and `diagnostics` output
  fields remain unchanged.

## Repository Evidence

- `crates/pine-runtime/src/strategy/broker/order_book.rs` contains the
  internal pending-order facade.
- `crates/pine-runtime/src/strategy/broker/ledger.rs` contains the internal
  open-trade ledger, net-position helper, and FIFO allocation helpers.
- `crates/pine-runtime/src/strategy/broker/fills.rs` centralizes current
  supported fill-side public order, trade, position, flat-state, and open-long
  legacy-state writes.
- `crates/pine-runtime/src/strategy/broker/accounting.rs` keeps equity
  snapshot recording in `record_equity`.
- `BrokerState::result` still returns the same public `StrategyResult` shape by
  cloning `orders`, `trades`, `position`, `equity`, and `diagnostics`.
- `cargo run -q -p pine-cli -- matrix` still reports strategy compatibility as
  the existing fixture-backed partial `strategy.entry`, `strategy.close`,
  `strategy.close_all`, `strategy.cancel`, `strategy.cancel_all`, and
  supported `strategy.exit` subset. Broader `strategy.*` order behavior remains
  unsupported.

## Verification

The closeout slice used the same behavior-preserving gate as the Stage 8
implementation slices:

```text
git diff --check
cargo test -p pine-runtime strategy --quiet
cargo test -p pine-runtime --test incremental --quiet
cargo test -p pine-cli runtime_outputs_match_golden_snapshots --quiet
cargo test -p pine-cli matrix_output_matches_golden_snapshot --quiet
cargo test -p pine-cli conformance --quiet
python3 scripts/check_structure.py
cargo clippy -p pine-runtime --all-targets -- -D warnings
cargo run -q -p pine-cli -- matrix
```

## Still Unsupported

- Same-direction pyramiding and multiple runtime entries.
- Short entries, short positions, and automatic reversals.
- Generic `strategy.order()`.
- Custom OCA policy and public pending-order state.
- Public open-trade or order-book schema expansion.
- Deriving public cash, position, and trade metrics exclusively from the
  internal ledger.
- Entry-relative same-calculation `strategy.exit` attachment using `profit`,
  `loss`, or `trail_points`.

## Next Direction Boundary

Stage 8 should stop here. The next work should open a new staged direction
instead of continuing as internal cleanup.

Reasonable next directions are:

- internal-only `StrategyPublicEvents` container migration, which requires
  updating tests that currently inspect `BrokerState` public-output fields
  directly;
- a fixture-backed Pine compatibility widening, starting with one official
  strategy behavior and landing runtime, semantic, conformance, host, docs, and
  release evidence atomically;
- a focused official-parity audit for the next unsupported strategy subset
  before implementation.

Do not widen strategy support from the Stage 8 document alone.

# Phase S Audit: Strategy Exit Trailing Stops

Status: closed for the current fixture-backed trailing-stop subset.

Phase S added the first deterministic `strategy.exit` trailing-stop
implementation for the existing long-only, no-pyramiding, one-pending-exit
broker. The compatibility claim remains partial and is tied to
`tests/fixtures/conformance.tsv`, semantic fixtures, runtime fixtures and
snapshots, incremental parity, host binding tests, docs, and the closeout
release gate.

## Completed Slices

- Slice 0 locked the Phase R baseline, documented the selected trailing-stop
  subset, and kept all trailing forms unsupported before runtime behavior
  existed.
- Slice 1 added trailing argument names to the builtin signature and hardened
  unsupported diagnostics without widening semantic support.
- Slice 2 classified trailing activation and offset argument families while
  keeping the standalone analyzer gate negative.
- Slice 3 added internal broker pending state for trailing exits, including
  placement identity, mutable active state, replacement behavior, validation,
  and close cancellation.
- Slice 4 routed strict trailing-only runtime calls into broker placement and
  guarded malformed HIR so trailing arguments cannot silently fall through to
  fixed stop/limit/profit/loss behavior.
- Slice 5 evaluated trailing activation, no-fill activation bars, upward-only
  ratchets, and active-stop fills inside the broker.
- Slice 6 enabled the two positive semantic forms and added runtime fixtures,
  golden snapshots, and incremental append coverage for trailing behavior.
- Slice 7 added CLI, Python, and WASM host parity tests for the same trailing
  fixture without binding-level broker logic.
- Slice 8 synchronized conformance metadata, matrix snapshot, maintainer docs,
  release notes, and roadmap status.
- Slice 9 added this audit, closed the execution plan, and ran the release
  verification gate.

## Supported Surface

The source of truth is `tests/fixtures/conformance.tsv`.

- `strategy.exit` remains partial.
- Existing single-trigger stop, limit, profit, and loss exits remain supported.
- Existing one-downside/one-upside brackets remain supported:
  - `stop + limit`
  - `stop + profit`
  - `loss + limit`
  - `loss + profit`
- Supported trailing forms are exactly:
  - `trail_price + trail_offset`
  - `trail_points + trail_offset`
- `trail_price` is an explicit activation price.
- `trail_points` converts once at placement time to
  `strategy.position_avg_price + trail_points * syminfo.mintick`.
- `trail_offset` converts once at placement time to
  `trail_offset * syminfo.mintick`.
- A trailing exit is one broker-owned pending full-position exit. Repeating an
  identical trailing call preserves the original eligibility bar and any active
  trailing state. Changing the exit identity or trailing specification replaces
  the pending exit, resets it to inactive, and resets eligibility.
- New and replaced trailing exits are not eligible on the creation or
  replacement bar.
- An inactive trailing exit activates on a later eligible historical bar when
  `high >= activation_price`, sets the active stop to
  `high - offset_distance`, and does not fill on the activation bar.
- On later bars, an active trailing exit fills first when `low <= active_stop`.
  If it does not fill, it ratchets to
  `max(active_stop, high - offset_distance)`. The stop never decreases.
- A filled trailing exit emits exactly one `strategy.exit` order event using the
  exit id, records one closed trade under the source entry id, clears the
  position, and updates normal position and equity snapshots.

## Unsupported Boundaries

The following remain fixture-backed unsupported:

- Combining trailing exits with fixed `stop`, `limit`, `profit`, or `loss`
  triggers.
- Calls with both `trail_price` and `trail_points`.
- Calls with `trail_price` or `trail_points` but no `trail_offset`.
- Calls with `trail_offset` but no activation argument.
- Partial exits, `qty`, `qty_percent`, and reservation behavior.
- Missing-entry pre-placement.
- Strategy order functions beyond the supported `strategy.entry`,
  `strategy.close`, and `strategy.exit` subset.
- Multiple entries, pyramiding, short exposure, and reversals.
- Multiple independent pending exits and public pending-order records.
- Commission, slippage, margin, currency conversion, richer sizing, strategy
  alerts, and realtime broker rollback.

## Public Output And Host Behavior

Phase S did not add top-level runtime JSON fields, Python dictionary keys, WASM
JSON fields, public pending-order records, trailing-state metadata,
partial-fill fields, exit-reason fields, or a runtime schema bump. Runtime
output remains `schemaVersion: 3`.

Public strategy output remains:

```text
strategy: {
  orders: [],
  trades: [],
  position: [],
  equity: [],
  diagnostics: []
}
```

CLI and WASM share `public_runtime_result_json`; Python maps the same
`StrategyResult` into native dictionaries. Host tests cover a shared
`trail_price + trail_offset` fixture and assert one exit order event, one
closed trade, the expected fill price, and unchanged output shape.

## Fixture Evidence

Compatibility matrix rows:

- `strategy`: `partial`
- `strategy.entry`: `partial`
- `strategy.close`: `partial`
- `strategy equity`: `partial`
- `strategy.position_size`: `partial`
- `strategy.position_avg_price`: `partial`
- `strategy.openprofit`: `partial`
- `strategy.netprofit`: `partial`
- `strategy.equity`: `partial`
- `strategy.closedtrades`: `partial`
- `strategy.opentrades`: `partial`
- `strategy.exit`: `partial`
- `strategy.*`: `unsupported`

Positive semantic fixtures:

- `tests/fixtures/sema/supported_strategy_exit_trail_price.pine`
- `tests/fixtures/sema/supported_strategy_exit_trail_points.pine`

Unsupported semantic fixtures that remain intentionally negative:

- `tests/fixtures/sema/unsupported_strategy_exit_trailing.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_profit_trailing.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_trail_price_only.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_trail_points_only.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_trail_offset_only.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_trail_price_points.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_trailing_bracket.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_trailing_partial_quantity.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_trailing_indicator.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_trailing_function_side_effect.pine`
- `tests/fixtures/sema/unsupported_request_strategy_trailing_exit.pine`
- Existing unsupported same-side, 3+ trigger, partial quantity, and
  missing-entry fixtures remain negative.

Runtime fixtures and snapshots:

- `tests/fixtures/runtime/strategy_exit_trail_price_fill.pine`
- `tests/fixtures/runtime/strategy_exit_trail_points_fill.pine`
- `tests/fixtures/runtime/strategy_exit_trailing_activation_bar.pine`
- `tests/fixtures/runtime/strategy_exit_trailing_ratchet.pine`
- `tests/fixtures/runtime/strategy_exit_trailing_repeated.pine`
- `tests/fixtures/runtime/strategy_exit_trailing_replacement.pine`
- `tests/fixtures/runtime/strategy_exit_trailing_invalid.pine`
- `tests/fixtures/runtime/strategy_exit_trailing_close_cancel.pine`
- `tests/fixtures/runtime/strategy_exit_trailing_interactions.pine`
- `tests/fixtures/runtime/strategy_exit_trailing_state.pine`
- `tests/fixtures/runtime/strategy_exit_trailing_bars.csv`
- `tests/snapshots/runtime_strategy_exit_trail_price_fill.json`
- `tests/snapshots/runtime_strategy_exit_trail_points_fill.json`
- `tests/snapshots/runtime_strategy_exit_trailing_activation_bar.json`
- `tests/snapshots/runtime_strategy_exit_trailing_ratchet.json`
- `tests/snapshots/runtime_strategy_exit_trailing_repeated.json`
- `tests/snapshots/runtime_strategy_exit_trailing_replacement.json`
- `tests/snapshots/runtime_strategy_exit_trailing_invalid.json`
- `tests/snapshots/runtime_strategy_exit_trailing_close_cancel.json`
- `tests/snapshots/runtime_strategy_exit_trailing_interactions.json`
- `tests/snapshots/runtime_strategy_exit_trailing_state.json`

Host and append evidence:

- `crates/pine-cli/src/main.rs` includes golden runtime snapshots for all
  trailing fixtures and a targeted host parity assertion for the trailing price
  fill fixture.
- `crates/pine-wasm/src/tests/mod.rs` asserts the same trailing fixture JSON
  contract through the WASM host surface.
- `python/tests/test_bindings.py` asserts the same trailing fixture contract as
  a native dictionary and checks unchanged top-level and strategy keys.
- `crates/pine-runtime/tests/incremental.rs` runs trailing fixtures through
  full historical and incremental append execution.

## Verification Results

Slice-level verification included:

```text
cargo fmt
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-runtime --test profile_fixtures
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/pine_compat_runtime-0.1.0-cp310-abi3-manylinux_2_35_x86_64.whl
python3 -m pytest python/tests
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
cargo test -p pine-cli matrix_output_matches_golden_snapshot
git diff --check
```

Snapshot refresh commands were run only when public runtime or matrix snapshots
intentionally changed:

```text
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
```

The closeout verification commands are:

```text
git diff --check
scripts/verify.sh
```

Closeout summary:

- `git diff --check`: passed with no output.
- `scripts/verify.sh`: passed. The script ran `cargo fmt --check`,
  `cargo clippy --workspace --all-targets -- -D warnings`,
  `cargo test --workspace`, `python3 scripts/check_structure.py`,
  `cargo check -p pine-wasm --target wasm32-unknown-unknown`,
  `maturin build --manifest-path crates/pine-python/Cargo.toml --out dist`,
  `python3 -m pip install --force-reinstall dist/*.whl`, and
  `python3 -m pytest python/tests`.

## Deferred Broker Tails

- Partial exits, `qty`, `qty_percent`, and reservation behavior.
- Missing-entry pre-placement.
- Multiple entries, pyramiding, short exposure, and reversals.
- Multiple independent pending exits and public pending-order records.
- Commission, slippage, margin, currency conversion, and richer sizing.
- Strategy alerts and realtime broker rollback.

The next narrow strategy maintenance target should be selected from these
deferred broker tails. Phase S does not start that follow-up work.

# Phase N Audit: Strategy Exit Profit And Loss

Status: closed for the current fixture-backed strategy exit profit/loss subset.

Phase N widened the Phase M long-only strategy exit lifecycle with narrow
`strategy.exit` tick-distance helpers. The compatibility claim remains
intentionally partial and is tied to `tests/fixtures/conformance.tsv`, runtime
snapshots, semantic fixtures, host binding tests, and the closeout release gate.

## Completed Slices

- Slice 0 locked the Phase M baseline and selected profit-only and loss-only
  exits as the first Phase N executable target. Mixed trigger, trailing,
  partial quantity, and missing-entry forms stayed fixture-backed unsupported.
- Slice 1 added semantic staging for accepted `profit` and `loss` calls while
  unsupported `strategy.exit` variants continued to produce stable diagnostics.
- Slice 2 added broker helpers that convert positive tick distances to
  entry-relative prices using the fixed default `syminfo.mintick` subset.
- Slice 3 routed runtime `strategy.exit(..., profit=...)` and
  `strategy.exit(..., loss=...)` calls through those broker helpers.
- Slice 4 added runtime fixtures, golden snapshots, conformance metadata, and
  documentation for profit-only and loss-only exits.
- Slice 5 hardened the CLI, Python, and WASM public contracts for representative
  profit/loss exits.
- Slice 6 added interaction coverage for branch, switch, for, while, strategy
  state reads, history reads, and incremental append execution.
- Slice 7 closed the bracket design gate by keeping every combined trigger form
  unsupported for Phase N.
- Slice 8 closed the audit and synchronized release, roadmap, conformance, and
  semantic documentation with the fixture-backed Phase N surface.

## Supported Surface

The source of truth is `tests/fixtures/conformance.tsv`.

- `strategy.exit` remains partial. In addition to the Phase M stop-only and
  limit-only forms, Phase N supports
  `strategy.exit(id, from_entry, profit=ticks)` and
  `strategy.exit(id, from_entry, loss=ticks)`.
- The call is strategy-mode-only and uses the current long-only broker model:
  one net long entry, one broker-owned pending full-position exit, and no
  pyramiding or short exposure.
- `profit` and `loss` must evaluate to finite positive numeric tick distances.
  Phase N uses the same fixed default `syminfo.mintick` subset as
  `math.round_to_mintick`.
- Profit exits convert to
  `strategy.position_avg_price + ticks * syminfo.mintick` and reuse the Phase M
  limit-trigger path.
- Loss exits convert to
  `strategy.position_avg_price - ticks * syminfo.mintick` and reuse the Phase M
  stop-trigger path.
- Supported exits can be created only for the matching current long entry.
  Missing or mismatched entries produce stable strategy diagnostics and do not
  create orphan pending exits.
- Repeating an unchanged accepted exit call preserves the original eligibility
  bar. Replacing the exit with a different supported trigger creates a new
  pending exit that is not eligible on the replacement bar.
- New or replaced pending exits are not eligible on the same bar. Loss-derived
  and stop exits fill on a later historical bar when `low <= exit_price`;
  profit-derived and limit exits fill on a later historical bar when
  `high >= exit_price`.
- Filled exits close the full current long position, append a `strategy.exit`
  order event with the exit id, record a closed trade under the source entry id,
  clear the position, and update the normal equity snapshot.

Unsupported Phase N variants remain explicit:

- combined trigger brackets: `stop + limit`, `profit + loss`, `stop + profit`,
  `limit + loss`, `stop + loss`, `limit + profit`, and three-trigger calls.
- trailing stops.
- partial exits and quantity reservation behavior.
- missing-entry pre-placement and multiple pending exits.
- short entries, reversals, and short exposure.
- `strategy.order` and richer order modification semantics.
- commission, slippage, margin, currency conversion, cash sizing, contracts,
  and percent-of-equity sizing.
- strategy closed-trade and open-trade namespaces.
- strategy alerts and alert placeholders.
- realtime strategy execution and forming-bar broker rollback.
- host-specific broker APIs or chart UI behavior outside the public runtime
  contract.

## Public Output And Host Behavior

Phase N did not add top-level runtime JSON fields, Python dictionary keys, WASM
JSON fields, public pending-order records, partial-fill fields, or exit-reason
fields. Runtime output remains `schemaVersion: 3`.

Filled profit/loss exits use the existing strategy output contract:

```text
strategy: {
  orders: [],
  trades: [],
  position: [],
  equity: [],
  diagnostics: []
}
```

CLI and WASM share `public_runtime_result_json`; Python maps the same strategy
result into native dictionaries. Host tests cover representative profit and
loss exit contracts through CLI snapshots, Python dictionaries, and WASM JSON.

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
- `strategy.exit`: `partial`
- `strategy.*`: `unsupported`

Runtime fixtures and snapshots:

- `tests/fixtures/runtime/strategy_exit_stop.pine`
- `tests/fixtures/runtime/strategy_exit_limit.pine`
- `tests/fixtures/runtime/strategy_exit_profit.pine`
- `tests/fixtures/runtime/strategy_exit_loss.pine`
- `tests/fixtures/runtime/strategy_exit_interactions.pine`
- `tests/fixtures/runtime/strategy_exit_profit_loss_interactions.pine`
- `tests/snapshots/runtime_strategy_exit_stop.json`
- `tests/snapshots/runtime_strategy_exit_limit.json`
- `tests/snapshots/runtime_strategy_exit_profit.json`
- `tests/snapshots/runtime_strategy_exit_loss.json`
- `tests/snapshots/runtime_strategy_exit_interactions.json`
- `tests/snapshots/runtime_strategy_exit_profit_loss_interactions.json`

Semantic fixtures:

- `tests/fixtures/sema/supported_strategy_exit_stop.pine`
- `tests/fixtures/sema/supported_strategy_exit_limit.pine`
- `tests/fixtures/sema/supported_strategy_exit_profit.pine`
- `tests/fixtures/sema/supported_strategy_exit_loss.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_stop_limit.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_profit_loss.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_stop_profit.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_limit_loss.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_stop_loss.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_limit_profit.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_three_triggers.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_profit_qty.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_loss_qty_percent.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_trailing.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_profit_trailing.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_partial_quantity.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_missing_id.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_function_side_effect.pine`
- `tests/fixtures/sema/unsupported_request_strategy_exit.pine`

Host and append evidence:

- `crates/pine-cli/src/main.rs` includes golden runtime snapshots for profit,
  loss, and interaction fixtures.
- `crates/pine-wasm/src/tests/mod.rs` asserts representative profit and loss
  exit JSON contracts.
- `python/tests/test_bindings.py` asserts representative profit and loss exit
  dictionary contracts.
- `crates/pine-runtime/tests/incremental.rs` runs the profit/loss runtime
  fixtures through full historical and incremental append execution.

## Verification Results

Slice-level verification included:

```text
cargo fmt --check
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-runtime --test profile_fixtures
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
python3 -m pytest python/tests
git diff --check
```

Snapshot refresh commands were run only when public runtime or matrix snapshots
changed:

```text
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
```

The closeout verification command was:

```text
git diff --check
scripts/verify.sh
```

It passed on the closeout workspace. This gate includes `cargo fmt --check`,
`cargo clippy --workspace --all-targets -- -D warnings`,
`cargo test --workspace`, `python3 scripts/check_structure.py`,
`cargo check -p pine-wasm --target wasm32-unknown-unknown`,
`maturin build --manifest-path crates/pine-python/Cargo.toml --out dist`,
wheel reinstall through `python3 -m pip install --force-reinstall dist/*.whl`,
and `python3 -m pytest python/tests`.

## Maintenance Tails

- Combined trigger brackets and same-bar high/low precedence.
- Trailing stops.
- Partial exits and quantity reservation behavior.
- Missing-entry pre-placement and multiple pending exits.
- Short entries, reversals, and short exposure.
- `strategy.order` and richer order modification semantics.
- Multiple simultaneous entries and pyramiding.
- Commission, slippage, margin, currency conversion, cash sizing, contracts,
  and percent-of-equity sizing.
- Strategy closed-trade and open-trade namespaces.
- Strategy alerts and alert placeholders.
- Realtime strategy execution and forming-bar broker rollback.
- Host-specific broker APIs or chart UI behavior outside the public runtime
  contract.

Recommended next stage: keep future strategy work as maintenance slices unless
a larger broker phase is deliberately opened for brackets, partial exits,
multiple pending exits, or realtime broker rollback.

## Structure Check

Strategy declaration and order semantic validation is owned by
`crates/pine-sema/src/analyzer/strategy.rs`. Built-in signatures are registered
in `crates/pine-builtins`. Strategy-specific runtime state is owned by
`crates/pine-runtime/src/strategy`, and public strategy result structs are in
`crates/pine-runtime/src/output/strategy.rs`.

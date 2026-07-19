# Phase U Audit: Strategy Exit Partial Quantity

Status: closed for the current fixture-backed fixed-quantity
`strategy.exit` subset.

Phase U added deterministic absolute `qty` support to the existing
long-only, no-pyramiding, one-pending-exit `strategy.exit` broker. The
compatibility claim remains partial and is tied to
`tests/fixtures/conformance.tsv`, semantic fixtures, runtime fixtures and
snapshots, incremental parity, CLI/Python/WASM host tests, docs, and the
closeout release gate.

## Completed Slices

- Slice 0 locked the Phase S strategy-exit baseline, selected fixed `qty` as
  the first quantity subset, deferred `qty_percent`, and confirmed no public
  strategy output schema bump was needed.
- Slice 1 added negative semantic guardrails for `qty`, `qty_percent`, and
  quantity arguments combined with unsupported trigger families while keeping
  all quantity calls unsupported.
- Slice 2 added internal pending-exit quantity intent with
  `PendingExitQuantity::Full` and `PendingExitQuantity::Fixed(f64)`, quantity
  identity, fixed-quantity placement helpers, and invalid-quantity diagnostics
  behind the still-closed analyzer gate.
- Slice 3 made broker fills close only the selected quantity, preserve the
  remaining long position when partial, and keep full-exit behavior unchanged
  when quantity is omitted or clamps to the whole position.
- Slice 4 opened analyzer and runtime support atomically for
  `strategy.exit(..., qty=...)` on the trigger families already supported
  before Phase U, while leaving `qty_percent` unsupported.
- Slice 5 added runtime fixtures, golden snapshots, and incremental append
  coverage for partial stop, limit, bracket, trailing, full-clamp, repeated,
  replacement, and state-variable behavior.
- Slice 6 added representative CLI, Python, and WASM host parity tests for the
  same partial fixed-quantity fixture and confirmed the public output shape
  remains unchanged.
- Slice 7 explicitly deferred `qty_percent` with semantic fixtures covering
  both standalone `qty_percent` and mixed `qty` plus `qty_percent` calls.
- Slice 8 synchronized conformance metadata, matrix snapshot, semantic docs,
  builtin signatures, release notes, and roadmap wording.
- Slice 9 added this audit, closed the execution plan and roadmap status, and
  ran focused verification plus the release gate.

## Supported Surface

The source of truth is `tests/fixtures/conformance.tsv`.

- `strategy.exit` remains partial.
- Existing single-trigger exits remain supported:
  - `stop`
  - `limit`
  - `profit`
  - `loss`
- Existing one-downside/one-upside brackets remain supported:
  - `stop + limit`
  - `stop + profit`
  - `loss + limit`
  - `loss + profit`
- Existing trailing exits remain supported:
  - `trail_price + trail_offset`
  - `trail_points + trail_offset`
- Phase U adds optional `qty` to each supported trigger family above.
- `qty` is evaluated once at placement time.
- `qty` must evaluate to a finite positive number.
- Omitted `qty` keeps the previous full-position exit behavior.
- On fill, fixed quantity closes `min(qty, current position size)`.
- A fixed quantity greater than or equal to the current position size closes
  the whole position.
- A fixed quantity smaller than the current position size leaves the remaining
  long position open at the same average price and clears the filled pending
  exit.
- Partial fills emit one existing `strategy.exit` order event and one existing
  closed-trade record using the closed quantity.
- `strategy.closedtrades` increases by one per filled partial exit.
- `strategy.opentrades` remains `1` after a partial fill while any supported
  long position remains open, and becomes `0` only when the final remaining
  position closes.

## Unsupported Boundaries

The following remain intentionally out of the Phase U compatibility claim:

- `qty_percent`.
- Quantity reservation across multiple exits.
- Multiple independent pending exits.
- Missing-entry pre-placement.
- Same-side bracket pairs `stop + loss` and `limit + profit`.
- 3+ trigger calls and invalid trailing combinations.
- Multiple entries, pyramiding, short exposure, and reversals.
- `strategy.order`, richer order modification, OCA behavior, comments, alert
  messages, and strategy alert delivery.
- Commission, slippage, margin, currency conversion, percent-of-equity sizing,
  cash sizing, contracts sizing, and custom tick-size host metadata.
- Public pending-order records, remaining-quantity fields, partial-fill fields,
  exit-reason fields, or a runtime schema bump.
- Realtime strategy execution, forming-bar broker rollback, and intrabar path
  reconstruction.

## Public Output And Host Behavior

Phase U does not add top-level runtime JSON fields, Python dictionary keys,
WASM JSON fields, public pending-order records, remaining-quantity fields,
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
`StrategyResult` into native dictionaries. Host tests cover
`tests/fixtures/runtime/strategy_exit_qty_stop_partial.pine` and assert the
partial exit order/trade quantity, remaining position, and unchanged public
strategy keys.

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

Positive semantic fixtures for fixed `qty`:

- `tests/fixtures/sema/supported_strategy_exit_qty_stop.pine`
- `tests/fixtures/sema/supported_strategy_exit_qty_bracket.pine`
- `tests/fixtures/sema/supported_strategy_exit_qty_trailing.pine`

Unsupported semantic fixtures that remain intentionally negative:

- `tests/fixtures/sema/unsupported_strategy_exit_qty_percent.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_qty_and_qty_percent.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_qty_same_side.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_partial_quantity.pine`
- Existing unsupported same-side, 3+ trigger, invalid trailing, indicator,
  UDF side-effect, requested-context, and missing-entry fixtures remain
  negative.

Runtime fixtures and snapshots:

- `tests/fixtures/runtime/strategy_exit_qty_stop_partial.pine`
- `tests/fixtures/runtime/strategy_exit_qty_limit_partial.pine`
- `tests/fixtures/runtime/strategy_exit_qty_bracket_partial.pine`
- `tests/fixtures/runtime/strategy_exit_qty_trailing_partial.pine`
- `tests/fixtures/runtime/strategy_exit_qty_full_clamp.pine`
- `tests/fixtures/runtime/strategy_exit_qty_repeated.pine`
- `tests/fixtures/runtime/strategy_exit_qty_replacement.pine`
- `tests/fixtures/runtime/strategy_exit_qty_state.pine`
- `tests/snapshots/runtime_strategy_exit_qty_stop_partial.json`
- `tests/snapshots/runtime_strategy_exit_qty_limit_partial.json`
- `tests/snapshots/runtime_strategy_exit_qty_bracket_partial.json`
- `tests/snapshots/runtime_strategy_exit_qty_trailing_partial.json`
- `tests/snapshots/runtime_strategy_exit_qty_full_clamp.json`
- `tests/snapshots/runtime_strategy_exit_qty_repeated.json`
- `tests/snapshots/runtime_strategy_exit_qty_replacement.json`
- `tests/snapshots/runtime_strategy_exit_qty_state.json`

Host and append evidence:

- `crates/pine-cli/src/main.rs` includes golden runtime snapshots for all
  fixed-quantity runtime fixtures and a targeted host parity assertion for the
  partial stop fixture.
- `crates/pine-wasm/src/tests/mod.rs` asserts the same partial stop fixture JSON
  contract through the WASM host surface.
- `python/tests/test_bindings.py` asserts the same partial stop fixture contract
  as a native dictionary and checks unchanged top-level and strategy keys.
- `crates/pine-runtime/tests/incremental.rs` runs the fixed-quantity fixtures
  through full historical and incremental append execution.

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
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/*.whl
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

The closeout verification command is:

```text
scripts/verify.sh
```

Focused verification and the closeout release gate passed on the Phase U
closeout workspace.
